# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import datetime, timedelta
from functools import partial
from itertools import groupby

from odoo import api, fields, models, SUPERUSER_ID, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.misc import formatLang, get_lang
from odoo.osv import expression
from odoo.tools import float_is_zero, float_compare

from werkzeug.urls import url_encode


class SaleReturn(models.Model):
    _name = 'sale.return'
    _inherit = ['portal.mixin', 'mail.thread', 'mail.activity.mixin', 'utm.mixin']
    _description = "Sales Return"
    _order = 'id desc'

    @api.depends('order_line.price_total')
    def _amount_all(self):
        for order in self:
            amount_untaxed = amount_tax = 0.0
            for line in order.order_line:
                amount_untaxed += line.price_subtotal
                amount_tax += line.price_tax
            order.update({
                'amount_untaxed': order.amount_untaxed,
                'amount_tax': order.amount_tax,
                'amount_total': amount_untaxed + amount_tax,
            })

    name = fields.Char(string='Order Reference', required=True, copy=False, readonly=True,
                       states={'draft': [('readonly', False)]}, index=True, default=lambda self: _('New'))
    origin = fields.Char(string='Source Document',
                         help="Reference of the document that generated this Return order request.")
    client_order_ref = fields.Char(string='Customer Reference', copy=False)
    reference = fields.Char(string='Payment Ref.', copy=False,
                            help='The payment communication of this sale order.')
    state = fields.Selection([
        ('draft', 'Quotation'),
        ('return', 'Return Order'),
        ('done', 'Locked'),
        ('cancel', 'Cancelled'),
    ], string='Status', readonly=True, copy=False, index=True, tracking=3, default='draft')
    date_order = fields.Datetime(string='Order Date', required=True, readonly=True, index=True,
                                 states={'draft': [('readonly', False)]}, copy=False,
                                 default=fields.Datetime.now,
                                 help="Creation date of draft/sent orders,\nConfirmation date of confirmed orders.")
    validity_date = fields.Date(string='Expiration', readonly=True, copy=False,
                                states={'draft': [('readonly', False)]}, )

    create_date = fields.Datetime(string='Creation Date', readonly=True, index=True,
                                  help="Date on which return order is created.")
    credit_note_done = fields.Boolean()
    picking_delivered = fields.Boolean(compute="_compute_picking_ids")

    user_id = fields.Many2one(
        'res.users', string='Salesperson', index=True, tracking=2, default=lambda self: self.env.user,
        domain=lambda self: [('groups_id', 'in', self.env.ref('sales_team.group_sale_salesman').id)])

    def _default_sale_id(self):
        return self.env['sale.order'].search([], limit=1)

    sale_id = fields.Many2one("sale.order", string="Sale Order", )

    order_line = fields.One2many('sale.return.line', 'order_id', string='Order Lines',
                                 states={'cancel': [('readonly', True)], 'done': [('readonly', True)]}, copy=True,
                                 auto_join=True)

    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)
    partner_id = fields.Many2one(
        'res.partner', string='Customer', readonly=True,
        states={'draft': [('readonly', False)]},
        required=True, change_default=True, index=True, tracking=1,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]", )
    pricelist_id = fields.Many2one(
        'product.pricelist', string='Pricelist', check_company=True,
        required=True, readonly=True, states={'draft': [('readonly', False)], 'sent': [('readonly', False)]},
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        help="If you change the pricelist, only newly added lines will be affected.")
    analytic_account_id = fields.Many2one('account.analytic.account', string='Analytic Account')
    commitment_date = fields.Datetime('Delivery Date',
                                      states={'draft': [('readonly', False)], 'sent': [('readonly', False)]},
                                      copy=False, readonly=True,
                                      help="This is the delivery date promised to the customer. "
                                           "If set, the delivery order will be scheduled based on "
                                           "this date rather than product lead times.")

    def _get_invoiced(self):
        for rec in self:
            rec.invoice_count = len(rec.invoice_ids.ids)

    invoice_count = fields.Integer(string='Invoice Count', readonly=True)
    invoice_ids = fields.Many2many("account.move", string='Invoices', readonly=True, copy=False)
    note = fields.Text('Terms and conditions')
    amount_untaxed = fields.Float(string='Untaxed Amount', store=True, readonly=True, compute='_amount_all', tracking=5)
    amount_tax = fields.Float(string='Taxes', store=True, readonly=True, compute='_amount_all')
    amount_total = fields.Float(string='Total', store=True, readonly=True, compute='_amount_all', tracking=4)

    @api.model
    def _get_default_team(self):
        return self.env['crm.team'].search([], limit=1)

    team_id = fields.Many2one(
        'crm.team', 'Sales Team',
        change_default=True, default=_get_default_team, check_company=True,  # Unrequired company
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")

    type_name = fields.Char('Type Name')

    @api.onchange('sale_id')
    def change_sale_id(self):
        if self.sale_id:
            lines = []
            self.partner_id = self.sale_id.partner_id.id
            self.warehouse_id = self.sale_id.warehouse_id.id
            self.user_id = self.sale_id.user_id.id
            self.team_id = self.sale_id.team_id.id
            self.company_id = self.sale_id.company_id.id
            self.analytic_account_id = self.sale_id.analytic_account_id.id
            self.commitment_date = self.sale_id.commitment_date
            self.client_order_ref = self.sale_id.client_order_ref
            self.validity_date = self.sale_id.validity_date
            for line in self.sale_id.order_line:
                values = {
                    'product_id': line.product_id.id,
                    'name': line.name,
                    'product_uom_qty': line.product_uom_qty,
                    'product_uom': line.product_uom.id,
                    'price_unit': line.price_unit,
                    'tax_id': [(6, 0, line.tax_id.ids)],
                }
                lines.append((0, 0, values))
            self.order_line = None
            self.order_line = lines
            #
            # lines = []
            # for val in self.sale_order_id.order_line:
            #     lines.append((0, 0,
            #                   {   'product_id': val.product_id.id, 'qty': val.product_uom_qty }
            #                   ))
            #
            # self.delivery_order_lines = None
            # self.delivery_order_lines = lines

            # self.order_line = lines

    def create_credit_note(self):
        self.ensure_one()

        journal = self.env['account.journal'].search([('type', '=', 'sale')], limit=1)
        if not journal:
            raise UserError(_('Please define an accounting sales journal for the company %s (%s).') % (
                self.company_id.name, self.company_id.id))

        lines = []
        for order_line in self.order_line:
            vals = {
                'product_id': order_line.product_id.id,
                'analytic_account_id': self.analytic_account_id.id,
                'quantity': order_line.product_uom_qty if self.amount_total >= 0 else -order_line.product_uom_qty,
                'discount': order_line.discount,
                'price_unit': order_line.price_unit,
                'name': order_line.product_id.display_name,
                'tax_ids': [(6, 0, order_line.tax_id.ids)],
            }

            lines.append((0, 0, vals))

        invoice_vals = {
            'ref': self.client_order_ref or '',
            'type': 'out_refund',
            'new_return_id': self.id,
            'narration': self.note,
            'invoice_user_id': self.user_id and self.user_id.id,
            'team_id': self.team_id.id,
            'partner_id': self.partner_id.id,
            'invoice_origin': self.name,
            'invoice_payment_ref': self.reference,
            'invoice_line_ids': lines,
        }
        invoice_id = self.env['account.move'].create(invoice_vals)
        self.invoice_ids = [(6, 0, [invoice_id.id])]
        view_id = self.env.ref('account.view_move_form').id
        self.credit_note_done = True
        return {
            'name': _('View Credit Note'),
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'target': 'current',
            'res_model': 'account.move',
            'view_id': view_id,
            'res_id': invoice_id.id
        }
        return result

    @api.onchange('company_id')
    def _onchange_company_id(self):
        if self.company_id:
            warehouse_id = self.env['ir.default'].get_model_defaults('sale.order').get('warehouse_id')
            self.warehouse_id = warehouse_id or self.env['stock.warehouse'].search(
                [('company_id', '=', self.company_id.id)], limit=1)

    @api.model
    def _default_warehouse_id(self):
        company = self.env.company.id
        print(">>>>>>>>>>>>>>>>>>>   ", company)
        warehouse_ids = self.env['stock.warehouse'].search([('company_id', '=', company)], limit=1)
        return warehouse_ids

    # @api.model
    # def _default_warehouse_id(self):
    #     company = self.env.company.id
    #     warehouse_ids = self.env['stock.warehouse'].search([('company_id', '=', company)], limit=1)
    #     return warehouse_ids
    # company = self.env.user.company_id.id
    # warehouse_ids = self.env['stock.warehouse'].search([], limit=1)
    # return warehouse_ids

    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Warehouse',
        required=True, readonly=True, states={'draft': [('readonly', False)]},
        default=_default_warehouse_id)

    picking_ids = fields.One2many('stock.picking', 'new_return_id', string='Transfers')
    move_ids = fields.One2many('account.move', 'new_return_id', string='Credit')

    #
    # _sql_constraints = [
    #     ('date_order_conditional_required',
    #      "CHECK( (state IN ('sale', 'done') AND date_order IS NOT NULL) OR state NOT IN ('sale', 'done') )",
    #      "A confirmed sales order requires a confirmation date."),
    # ]

    def unlink(self):
        for order in self:
            if order.state not in ('draft', 'cancel'):
                raise UserError(
                    _('You can not delete a sent quotation or a confirmed return order. You must first cancel it.'))
        return super(SaleReturn, self).unlink()

    @api.onchange('user_id')
    def onchange_user_id(self):
        if self.user_id and self.user_id.sale_team_id:
            self.team_id = self.user_id.sale_team_id

    @api.model
    def create(self, vals):
        if vals.get('name', _('New')) == _('New'):
            seq_date = None
            if 'date_order' in vals:
                seq_date = fields.Datetime.context_timestamp(self, fields.Datetime.to_datetime(vals['date_order']))
            if 'company_id' in vals:
                vals['name'] = self.env['ir.sequence'].with_context(force_company=vals['company_id']).next_by_code(
                    'sale.return', sequence_date=seq_date) or _('New')
            else:
                vals['name'] = self.env['ir.sequence'].next_by_code('sale.return', sequence_date=seq_date) or _('New')

            # Makes sure 'pricelist_id' are defined
            if any(f not in vals for f in ['pricelist_id']):
                partner = self.env['res.partner'].browse(vals.get('partner_id'))
                vals['pricelist_id'] = vals.setdefault('pricelist_id',
                                                       partner.property_product_pricelist and partner.property_product_pricelist.id)

        if 'warehouse_id' not in vals and 'company_id' in vals and vals.get('company_id') != self.env.company.id:
            vals['warehouse_id'] = self.env['stock.warehouse'].search([('company_id', '=', vals.get('company_id'))],
                                                                      limit=1).id

        return super(SaleReturn, self).create(vals)

    def name_get(self):
        if self._context.get('sale_show_partner_name'):
            res = []
            for order in self:
                name = order.name
                if order.partner_id.name:
                    name = '%s - %s' % (name, order.partner_id.name)
                res.append((order.id, name))
            return res
        return super(SaleReturn, self).name_get()

    @api.model
    def _name_search(self, name, args=None, operator='ilike', limit=100, name_get_uid=None):
        if self._context.get('sale_show_partner_name'):
            if operator == 'ilike' and not (name or '').strip():
                domain = []
            elif operator in ('ilike', 'like', '=', '=like', '=ilike'):
                domain = expression.AND([
                    args or [],
                    ['|', ('name', operator, name), ('partner_id.name', operator, name)]
                ])
                order_ids = self._search(domain, limit=limit, access_rights_uid=name_get_uid)
                return models.lazy_name_get(self.browse(order_ids).with_user(name_get_uid))
        return super(SaleReturn, self)._name_search(name, args=args, operator=operator, limit=limit,
                                                    name_get_uid=name_get_uid)

    def action_view_invoice(self):
        invoices = self.mapped('invoice_ids')
        action = self.env.ref('account.action_move_out_invoice_type').read()[0]
        if len(invoices) > 1:
            action['domain'] = [('id', 'in', invoices.ids)]
        elif len(invoices) == 1:
            form_view = [(self.env.ref('account.view_move_form').id, 'form')]
            if 'views' in action:
                action['views'] = form_view + [(state, view) for state, view in action['views'] if view != 'form']
            else:
                action['views'] = form_view
            action['res_id'] = invoices.id
        else:
            action = {'type': 'ir.actions.act_window_close'}

        context = {
            'default_type': 'out_invoice',
        }
        if len(self) == 1:
            context.update({
                'default_partner_id': self.partner_id.id,
                'default_invoice_origin': self.mapped('name'),
                'default_user_id': self.user_id.id,
            })
        action['context'] = context
        return action

    def action_draft(self):
        orders = self.filtered(lambda s: s.state in ['cancel'])
        return orders.write({
            'state': 'draft',
        })

    def action_cancel(self):
        return self.write({'state': 'cancel'})

    def action_done(self):
        # for order in self:
        #     tx = order.sudo().transaction_ids.get_last_transaction()
        #     if tx and tx.state == 'pending' and tx.acquirer_id.provider == 'transfer':
        #         tx._set_transaction_done()
        #         tx.write({'is_processed': True})
        return self.write({'state': 'done'})

    def action_unlock(self):
        self.write({'state': 'return'})

    def _action_confirm(self):
        """ Implementation of additionnal mecanism of Sales Order confirmation.
            This method should be extended when the confirmation should generated
            other documents. In this method, the SO are in 'sale' state (not yet 'done').
        """
        # create an analytic account if at least an expense product
        self._create_stock()
        if self.sale_id:
            for line in self.order_line:
                for s_line in self.sale_id.order_line:
                    if line.product_id == s_line.product_id and line.product_uom_qty > s_line.product_uom_qty:
                        raise ValidationError(_(
                            "Can not return Quantity more than [ %s ] sold for product [ %s ]" % (
                                s_line.product_uom_qty, line.product_id.name)))

        return True

    def action_confirm(self):
        if self._get_forbidden_state_confirm() & set(self.mapped('state')):
            raise UserError(_(
                'It is not allowed to confirm an order in the following states: %s'
            ) % (', '.join(self._get_forbidden_state_confirm())))

        for order in self.filtered(lambda order: order.partner_id not in order.message_partner_ids):
            order.message_subscribe([order.partner_id.id])
        self.write({
            'state': 'return',
            'date_order': fields.Datetime.now()
        })
        self._action_confirm()
        if self.env.user.has_group('sale.group_auto_done_setting'):
            self.action_done()
        return True

    def _get_forbidden_state_confirm(self):
        return {'done', 'cancel'}

    def _create_stock(self):
        pickings = self.mapped('picking_ids')
        picking_id = self.env["stock.picking"].create({
            'partner_id': self.partner_id.id,
            'origin': self.name,
            'scheduled_date': self.commitment_date if self.commitment_date else fields.Date.today(),
            'picking_type_id': self.env['stock.picking.type'].search([('code', '=', 'incoming')])[0].id,
            'location_dest_id': self.warehouse_id.lot_stock_id.id,
            'location_id': self.env['stock.location'].search([('usage', '=', 'customer')])[0].id,
        })
        for line in self.order_line:
            self.env['stock.move'].create({
                'picking_id': picking_id.id,
                'product_id': line.product_id.id,
                'name': line.product_id.name,
                'product_uom_qty': line.product_uom_qty,
                'location_dest_id': self.warehouse_id.lot_stock_id.id,
                'location_id': self.env['stock.location'].search([('usage', '=', 'customer')])[0].id,
                'product_uom': line.product_id.uom_id.id,
            })
            picking_id.scheduled_date = self.commitment_date if self.commitment_date else fields.Date.today()
            picking_id.action_confirm()
            picking_id.action_assign()

        self.picking_ids = [(6, 0, [picking_id.id])]

    def action_view_receipt(self):
        '''
        This function returns an action that display existing receipt orders
        of given sales order ids. It can either be a in a list or in a form
        view, if there is only one receipt order to show.
        '''
        action = self.env.ref('stock.action_picking_tree_all').read()[0]

        pickings = self.mapped('picking_ids')
        if len(pickings) > 1:
            action['domain'] = [('id', 'in', pickings.ids)]
        elif pickings:
            form_view = [(self.env.ref('stock.view_picking_form').id, 'form')]
            if 'views' in action:
                action['views'] = form_view + [(state, view) for state, view in action['views'] if view != 'form']
            else:
                action['views'] = form_view
            action['res_id'] = pickings.id
        # Prepare the context.
        picking_id = pickings.filtered(lambda l: l.picking_type_id.code == 'incoming')
        if picking_id:
            picking_id = picking_id[0]
        else:
            picking_id = pickings[0]
        action['context'] = dict(self._context, default_partner_id=self.partner_id.id, default_picking_id=picking_id.id,
                                 default_picking_type_id=picking_id.picking_type_id.id, default_origin=self.name,
                                 default_group_id=picking_id.group_id.id)
        return action

    def action_view_credit_note(self):
        view_id = self.env.ref('account.view_move_form').id
        # print(">>>>>>>>>>>>>> ", self.invoice_ids.id)
        return {
            'name': _('View Credit Note'),
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'target': 'current',
            'res_model': 'account.move',
            'view_id': view_id,
            'res_id': self.invoice_ids[0].id
        }

    receipts_count = fields.Integer(string='Receipt Orders', compute='_compute_picking_ids')
    credit_note_count = fields.Integer(string='Credit notes', compute='_compute_credit_note')

    @api.depends('picking_ids')
    def _compute_picking_ids(self):
        for rec in self:
            rec.receipts_count = len(rec.picking_ids)
            if rec.picking_ids:
                for pick in rec.picking_ids:
                    if pick.state == 'done':
                        rec.picking_delivered = True
                    else:
                        rec.picking_delivered = False
            else:
                rec.picking_delivered = False

    @api.depends('move_ids')
    def _compute_credit_note(self):
        for rec in self:
            rec.credit_note_count = len(rec.move_ids.ids)

    @api.onchange('partner_id')
    def onchange_partner_id(self):
        """
        Update the following fields when the partner is changed:
        - Pricelist
        - Payment terms
        - Invoice address
        - Delivery address
        - Sales Team
        """

        partner_user = self.partner_id.user_id or self.partner_id.commercial_partner_id.user_id
        values = {
            'pricelist_id': self.partner_id.property_product_pricelist and self.partner_id.property_product_pricelist.id or False,
        }
        user_id = partner_user.id
        if not self.env.context.get('not_self_saleperson'):
            user_id = user_id or self.env.uid
        if user_id and self.user_id.id != user_id:
            values['user_id'] = user_id

        if self.env['ir.config_parameter'].sudo().get_param(
                'account.use_invoice_terms') and self.env.company.invoice_terms:
            values['note'] = self.with_context(lang=self.partner_id.lang).env.company.invoice_terms
        if not self.env.context.get('not_self_saleperson') or not self.team_id:
            values['team_id'] = self.env['crm.team'].with_context(
                default_team_id=self.partner_id.team_id.id
            )._get_default_team_id(domain=['|', ('company_id', '=', self.company_id.id), ('company_id', '=', False)],
                                   user_id=user_id)
        self.update(values)


class SaleReturnLine(models.Model):
    _name = 'sale.return.line'
    _description = 'Rrturn Order Line'
    _order = 'order_id, sequence, id'
    _check_company_auto = True

    order_id = fields.Many2one('sale.return', string='Order Reference', required=False, ondelete='cascade', index=True,
                               copy=False)
    name = fields.Text(string='Description', required=True)
    sequence = fields.Integer(string='Sequence', default=10)

    invoice_lines = fields.Many2many('account.move.line', 'sale_return_line_invoice_rel', 'order_line_id',
                                     'invoice_line_id', string='Invoice Lines', copy=False)
    price_unit = fields.Float('Unit Price', required=False, digits='Product Price', default=0.0)

    price_subtotal = fields.Float(string='Subtotal', compute="_compute_amount", readonly=True, store=True)
    price_tax = fields.Float(string='Total Tax', compute="_compute_amount", readonly=True, store=True)
    price_total = fields.Float(string='Total', compute="_compute_amount", readonly=True, store=True)

    tax_id = fields.Many2many('account.tax', string='Taxes',
                              domain=['|', ('active', '=', False), ('active', '=', True)])

    discount = fields.Float(string='Discount (%)', digits='Discount', default=0.0)

    product_id = fields.Many2one(
        'product.product', string='Product', required=True,
        domain="[('sale_ok', '=', True), '|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        change_default=True, ondelete='restrict', check_company=True)  # Unrequired company
    product_template_id = fields.Many2one(
        'product.template', string='Product Template',
        related="product_id.product_tmpl_id", domain=[('sale_ok', '=', True)])
    product_updatable = fields.Boolean(string='Can Edit Product', readonly=True, default=True)

    product_uom_qty = fields.Float(string='Quantity', digits='Product Unit of Measure', required=False, default=1.0)
    product_uom = fields.Many2one('uom.uom', string='Unit of Measure',
                                  domain="[('category_id', '=', product_uom_category_id)]")
    product_uom_category_id = fields.Many2one(related='product_id.uom_id.category_id', readonly=True)
    # product_custom_attribute_value_ids = fields.One2many('product.attribute.custom.value', 'sale_return_line_id',
    #                                                      string="Custom Values")
    # product_no_variant_attribute_value_ids = fields.Many2many('product.template.attribute.value', string="Extra Values",
    #                                                           ondelete='restrict')

    # M2M holding the values of product.attribute with create_variant field set to 'no_variant'
    # It allows keeping track of the extra_price associated to those attribute values and add them to the SO line description

    order_partner_id = fields.Many2one(related='order_id.partner_id', store=True, string='Customer', readonly=False)
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)

    def _get_display_price(self, product):
        # TO DO: move me in master/saas-16 on sale.order
        # awa: don't know if it's still the case since we need the "product_no_variant_attribute_value_ids" field now
        # to be able to compute the full price

        # it is possible that a no_variant attribute is still in a variant if
        # the type of the attribute has been changed after creation.
        # no_variant_attributes_price_extra = [
        #     ptav.price_extra for ptav in self.product_no_variant_attribute_value_ids.filtered(
        #         lambda ptav:
        #         ptav.price_extra and
        #         ptav not in product.product_template_attribute_value_ids
        #     )
        # ]
        # if no_variant_attributes_price_extra:
        #     product = product.with_context(
        #         no_variant_attributes_price_extra=tuple(no_variant_attributes_price_extra)
        #     )

        if self.order_id.pricelist_id.discount_policy == 'with_discount':
            return product.with_context(pricelist=self.order_id.pricelist_id.id, uom=self.product_uom.id).price
        product_context = dict(self.env.context, partner_id=self.order_id.partner_id.id, date=self.order_id.date_order,
                               uom=self.product_uom.id)

        final_price, rule_id = self.order_id.pricelist_id.with_context(product_context).get_product_price_rule(
            product or self.product_id, self.product_uom_qty or 1.0, self.order_id.partner_id)
        base_price, currency = self.with_context(product_context)._get_real_price_currency(product, rule_id,
                                                                                           self.product_uom_qty,
                                                                                           self.product_uom,
                                                                                           self.order_id.pricelist_id.id)
        if currency != self.order_id.pricelist_id.currency_id:
            base_price = currency._convert(
                base_price, self.order_id.pricelist_id.currency_id,
                self.order_id.company_id or self.env.company, self.order_id.date_order or fields.Date.today())
        # negative discounts (= surcharge) are included in the display price
        return max(base_price, final_price)

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if not self.product_id:
            return

        # valid_values = self.product_id.product_tmpl_id.valid_product_template_attribute_line_ids.product_template_value_ids
        # remove the is_custom values that don't belong to this template
        # for pacv in self.product_custom_attribute_value_ids:
        #     if pacv.custom_product_template_attribute_value_id not in valid_values:
        #         self.product_custom_attribute_value_ids -= pacv
        #
        # # remove the no_variant attributes that don't belong to this template
        # for ptav in self.product_no_variant_attribute_value_ids:
        #     if ptav._origin not in valid_values:
        #         self.product_no_variant_attribute_value_ids -= ptav

        vals = {}
        if not self.product_uom or (self.product_id.uom_id.id != self.product_uom.id):
            vals['product_uom'] = self.product_id.uom_id
            vals['product_uom_qty'] = self.product_uom_qty or 1.0

        product = self.product_id.with_context(
            lang=get_lang(self.env, self.order_id.partner_id.lang).code,
            partner=self.order_id.partner_id,
            quantity=vals.get('product_uom_qty') or self.product_uom_qty,
            date=self.order_id.date_order,
            pricelist=self.order_id.pricelist_id.id,
            uom=self.product_uom.id
        )

        if self.order_id.pricelist_id and self.order_id.partner_id:
            vals['price_unit'] = self.env['account.tax']._fix_tax_included_price_company(
                self._get_display_price(product), product.taxes_id, self.tax_id, self.company_id)

        # self.price_unit = self.product_id.list_price
        # self.product_uom = self.product_id.uom_id.id
        # self.name = self.product_id.name
        if not self.name:
            vals['name'] = self.product_id.name

        self.update(vals)

    @api.depends('product_uom_qty', 'discount', 'price_unit', 'tax_id')
    def _compute_amount(self):
        """
        Compute the amounts of the SO line.
        """
        for line in self:
            price = line.price_unit * (1 - (line.discount or 0.0) / 100.0)
            taxes = line.tax_id.compute_all(price, False, line.product_uom_qty, product=line.product_id,
                                            partner=line.order_id.partner_id)
            line.update({
                'price_tax': sum(t.get('amount', 0.0) for t in taxes.get('taxes', [])),
                'price_total': taxes['total_included'],
                'price_subtotal': taxes['total_excluded'],
            })

    # def _get_sale_order_line_multiline_description_variants(self):
    #     """When using no_variant attributes or is_custom values, the product
    #     itself is not sufficient to create the description: we need to add
    #     information about those special attributes and values.
    #
    #     :return: the description related to special variant attributes/values
    #     :rtype: string
    #     """
    #     if not self.product_custom_attribute_value_ids and not self.product_no_variant_attribute_value_ids:
    #         return ""
    #
    #     name = "\n"
    #
    #     custom_ptavs = self.product_custom_attribute_value_ids.custom_product_template_attribute_value_id
    #     no_variant_ptavs = self.product_no_variant_attribute_value_ids._origin
    #
    #     # display the no_variant attributes, except those that are also
    #     # displayed by a custom (avoid duplicate description)
    #     for ptav in (no_variant_ptavs - custom_ptavs):
    #         name += "\n" + ptav.with_context(lang=self.order_id.partner_id.lang).display_name
    #
    #     # Sort the values according to _order settings, because it doesn't work for virtual records in onchange
    #     custom_values = sorted(self.product_custom_attribute_value_ids,
    #                            key=lambda r: (r.custom_product_template_attribute_value_id.id, r.id))
    #     # display the is_custom values
    #     for pacv in custom_values:
    #         name += "\n" + pacv.with_context(lang=self.order_id.partner_id.lang).display_name
    #
    #     return name
