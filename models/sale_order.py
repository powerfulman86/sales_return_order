from odoo import fields, models, api


class SaleOrder(models.Model):
    _inherit= 'sale.order'

    def action_confirm(self):
        sale_date = self.env['ir.config_parameter'].sudo().get_param('base_setup.sale_date')
        date = self.date_order
        res = super(SaleOrder, self).action_confirm()
        if sale_date == "True":
            self.date_order = date
        return res


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    sale_date = fields.Boolean(string="Sale Date",config_parameter='base_setup.sale_date')


