from odoo import fields, models, api


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    new_return_id = fields.Many2one(comodel_name='sale.return')


class AccountMove(models.Model):
    _inherit = 'account.move'

    new_return_id = fields.Many2one(comodel_name='sale.return')
