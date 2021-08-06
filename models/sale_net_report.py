# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import tools
from odoo import api, fields, models


class SaleNetReport(models.Model):
    _name = "sale.net.report"
    _description = "Sales Net Analysis Report"
    _auto = False
    # _rec_name = 'date'
    # _order = 'date desc'
    name = fields.Char('Order Reference', readonly=True)
    date = fields.Datetime('Order Date', readonly=True)
    product_id = fields.Many2one('product.product', 'Product Variant', readonly=True)
    product_uom = fields.Many2one('uom.uom', 'Unit of Measure', readonly=True)
    product_uom_qty = fields.Float('Qty Ordered', readonly=True)
    partner_id = fields.Many2one('res.partner', 'Customer', readonly=True)
    company_id = fields.Many2one('res.company', 'Company', readonly=True)
    price_total = fields.Float('Total', readonly=True)
    price_subtotal = fields.Float('Untaxed Total', readonly=True)
    product_tmpl_id = fields.Many2one('product.template', 'Product', readonly=True)
    categ_id = fields.Many2one('product.category', 'Product Category', readonly=True)
    analytic_account_id = fields.Many2one('account.analytic.account', 'Analytic Account', readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('sale', 'Order'),
        ('done', 'Done'),
        ('cancel', 'Cancelled'),
    ], string='Status', readonly=True)
    trans_type = fields.Selection([
        ('Sales Order', 'Sales Order'),
        ('Return Order', 'Return Order')
    ], string='Transaction Type', readonly=True)
    discount_amount = fields.Float('Discount Amount', readonly=True)

    def _query(self, with_clause='', fields={}, groupby='', from_clause=''):
        with_ = ("WITH %s" % with_clause) if with_clause else ""

        select_ = """
            min(l.id) as id,
            l.product_id as product_id,
            t.uom_id as product_uom,
            round(sum(l.product_uom_qty / u.factor * u2.factor),3) as product_uom_qty, 
            sum(l.price_total) as price_total,
            sum(l.price_subtotal)  as price_subtotal, 
            s.name as name,
            s.date_order as date,
			'Sales Order' as trans_type,
			s.analytic_account_id as analytic_account_id,
            s.state as state,
            s.partner_id as partner_id,
            t.categ_id as categ_id,
            p.product_tmpl_id,
            round(sum((l.price_unit * l.discount / 100.0 )),3) as discount_amount
        """

        for field in fields.values():
            select_ += field

        from_ = """
                sale_order_line l
                      join sale_order s on (l.order_id=s.id)
                      join res_partner partner on s.partner_id = partner.id
                        left join product_product p on (l.product_id=p.id)
                            left join product_template t on (p.product_tmpl_id=t.id)
                    left join uom_uom u on (u.id=l.product_uom)
                    left join uom_uom u2 on (u2.id=t.uom_id) 
                %s
        """ % from_clause

        groupby_ = """
            l.product_id,
            l.order_id,
            t.uom_id,
            t.categ_id,
            s.name,
            s.date_order,
            trans_type,
            s.analytic_account_id,
            s.partner_id,
            s.state,
            p.product_tmpl_id %s
        """ % groupby

        select2_ = """
                    min(l.id) as id,
                    l.product_id as product_id,
                    t.uom_id as product_uom,
                    round(sum(l.product_uom_qty / u.factor * u2.factor),3) *-1 as product_uom_qty, 
                    sum(l.price_total)*-1 as price_total,
                    sum(l.price_subtotal)*-1  as price_subtotal, 
                    s.name as name,
                    s.date_order as date,
        			'Return Order' as trans_type,
        			s.analytic_account_id as analytic_account_id,
                    s.state as state,
                    s.partner_id as partner_id,
                    t.categ_id as categ_id,
                    p.product_tmpl_id,
                    round(sum((l.price_unit * l.discount / 100.0 )),3) as discount_amount
                """

        for field in fields.values():
            select2_ += field

        from2_ = """
                        sale_return_line l
                              join sale_return s on (l.order_id=s.id)
                              join res_partner partner on s.partner_id = partner.id
                                left join product_product p on (l.product_id=p.id)
                                    left join product_template t on (p.product_tmpl_id=t.id)
                            left join uom_uom u on (u.id=l.product_uom)
                            left join uom_uom u2 on (u2.id=t.uom_id) 
                        %s
                """ % from_clause

        groupby2_ = """
                    l.product_id,
                    l.order_id,
                    t.uom_id,
                    t.categ_id,
                    s.name,
                    s.date_order,
                    trans_type,
                    s.analytic_account_id,
                    s.partner_id,
                    s.state,
                    p.product_tmpl_id %s
                """ % groupby

        select3_ = """
                    min(pol.id) as id,
                    pol.product_id as product_id,
                    pt.uom_id as product_uom,
                    round(sum(pol.qty / u.factor * u2.factor),3) *-1 as product_uom_qty, 
                    sum(pol.price_unit * pol.qty - pol.price_unit * pol.qty / 100 * pol.discount) as price_total,
                    sum(pol.price_unit * pol.qty - pol.price_unit * pol.qty / 100 * pol.discount)  as price_subtotal, 
                    po.name as name,
                    po.date_order as date,
                    'POS' as trans_type,
                    po.analytic_account_id as analytic_account_id,
                    po.state as state,
                    po.partner_id as partner_id,
                    pt.categ_id as categ_id,
                    pp.product_tmpl_id,
                    round(sum((pol.price_unit * pol.discount / 100.0 ) + cast(pol.extra_discount_value as numeric)),3) as discount_amount
                        """

        for field in fields.values():
            select3_ += field

        from3_ = """
                    pos_order_line pol
                    LEFT JOIN pos_order po ON po.id = pol.order_id
                    LEFT JOIN product_product pp ON pp.id = pol.product_id
                    LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id
                    left join uom_uom u on (u.id=pol.product_uom_id)
                    left join uom_uom u2 on (u2.id=pt.uom_id) 
                    left join res_partner partner on po.partner_id = partner.id
                    %s
            """ % from_clause

        groupby3_ = """
                    pol.product_id,
                    pt.uom_id, 
                    po.name,
                    po.date_order,
                    po.analytic_account_id,
                    po.state,
                    po.partner_id,
                    pt.categ_id,
                    pp.product_tmpl_id %s
                """ % groupby

        return '%s (SELECT %s FROM %s WHERE l.product_id IS NOT NULL GROUP BY %s Union SELECT %s FROM %s WHERE ' \
               'l.product_id IS NOT NULL GROUP BY %s Union SELECT %s FROM %s WHERE ' \
               'pol.product_id IS NOT NULL GROUP BY %s)' % (
                   with_, select_, from_, groupby_, select2_, from2_, groupby2_, select3_, from3_, groupby3_)

    def init(self):
        # self._table = sale_report
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""CREATE or REPLACE VIEW %s as (%s)""" % (self._table, self._query()))


class SaleNetReportProforma(models.AbstractModel):
    _name = 'sale.net.report_saleproforma'
    _description = 'Proforma Report'

    def _get_report_values(self, docids, data=None):
        docs = self.env['sale.net'].browse(docids)
        return {
            'doc_ids': docs.ids,
            'doc_model': 'sale.net',
            'docs': docs,
            'proforma': True
        }
