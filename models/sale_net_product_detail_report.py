# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import tools
from odoo import api, fields, models


class SaleNetProductDetailReport(models.Model):
    _name = "sale.net.product.detail.report"
    _description = "Sales Net Analysis Report By Product"
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
    user_id = fields.Many2one('res.users', 'Salesperson', readonly=True)
    price_total = fields.Float('Total', readonly=True)
    price_subtotal = fields.Float('Untaxed Total', readonly=True)
    product_tmpl_id = fields.Many2one('product.template', 'Product', readonly=True)
    categ_id = fields.Many2one('product.category', 'Product Category', readonly=True)
    nbr = fields.Integer('# of Lines', readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('sale', 'Order'),
        ('done', 'Done'),
        ('cancel', 'Cancelled'),
    ], string='Status', readonly=True)
    # trans_type = fields.Selection([
    #     ('Sales Order', 'Sales Order'),
    #     ('Return Order', 'Return Order')
    # ], string='Transaction Type', readonly=True)
    discount = fields.Float('Discount %', readonly=True)
    discount_amount = fields.Float('Discount Amount', readonly=True)
    order_id = fields.Integer('Order #', readonly=True)

    def _query(self, with_clause='', fields={}, groupby='', from_clause=''):
        with_ = ("WITH %s" % with_clause) if with_clause else ""

        select_ = """
            min(l.id) as id,
            l.product_id as product_id,
            t.uom_id as product_uom,
            round(sum(l.product_uom_qty / u.factor * u2.factor),3) as product_uom_qty, 
            sum(l.price_total) as price_total,
            sum(l.price_subtotal)  as price_subtotal, 
            count(*) as nbr,
            s.name as name,
            s.date_order as date, 
            s.state as state,
            s.partner_id as partner_id,
            t.categ_id as categ_id,
            p.product_tmpl_id,
            l.discount as discount,
            round(sum((l.price_unit * l.discount / 100.0 )),3) as discount_amount,	 
            s.id as order_id 
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
            s.partner_id,
            s.state,
            p.product_tmpl_id,
            l.discount,
            s.id %s 
        """ % groupby

        select2_ = """
                    min(l.id) as id,
                    l.product_id as product_id,
                    t.uom_id as product_uom,
                    round(sum(l.product_uom_qty / u.factor * u2.factor),3) as product_uom_qty, 
                    sum(l.price_total) as price_total,
                    sum(l.price_subtotal)  as price_subtotal, 
        			count(*) as nbr,
                    s.name as name,
                    s.date_order as date,
                    'Sales Return' as transtype, 
                    s.state as state,
                    s.partner_id as partner_id,
                    t.categ_id as categ_id,
                    p.product_tmpl_id,
                    l.discount as discount,
                    round(sum((l.price_unit * l.discount / 100.0 )),3) as discount_amount,	
                    s.id as order_id 
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
                    s.partner_id,
                    s.state,
                    p.product_tmpl_id,
                    l.discount,
                     s.id %s
                    
                """ % groupby

        return '%s (SELECT %s FROM %s WHERE l.product_id IS NOT NULL GROUP BY %s Union SELECT %s FROM %s WHERE ' \
               'l.product_id IS NOT NULL GROUP BY %s)' % (with_, select_, from_, groupby_, select2_, from2_, groupby2_)

    def init(self):
        # self._table = sale_report
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""CREATE or REPLACE VIEW %s as (%s)""" % (self._table, self._query()))


class SaleNetProductDetailReportProforma(models.AbstractModel):
    _name = 'sale.net.product.detail.report_saleproforma'
    _description = 'Proforma Report'

    def _get_report_values(self, docids, data=None):
        docs = self.env['sale.return'].browse(docids)
        return {
            'doc_ids': docs.ids,
            'doc_model': 'sale.net.product.detail',
            'docs': docs,
            'proforma': True
        }
