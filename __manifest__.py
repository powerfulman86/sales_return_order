# -*- coding: utf-8 -*-
{
    'name': "sales_return_order",
    'summary': """Sales Return order""",
    'description': """Sale Return Order""",
    'author': "CubicIt Egypt",
    'category': 'Sales',
    'version': '13.0.0.1',
    'depends': ['base', 'sale', 'stock'],
    'data': [
        'security/ir.model.access.csv',
        'data/data.xml',
        'views/sale_return.xml',
        'views/sale_return_report.xml',
        'views/sale_net_report.xml',
        'views/sale_net_product_detail_report.xml',
    ],

}
