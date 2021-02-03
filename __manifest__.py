# -*- coding: utf-8 -*-
{
    'name': "sales_return_order",
    'summary': """Sales Return order""",
    'description': """Sale Return Order""",
    'author': "",
    'category': 'Uncategorized',
    'version': '13.0.0.1',
    'depends': ['base', 'sale', 'purchase', 'stock'],

    'data': [
        'security/ir.model.access.csv',
        'data/data.xml',
        'views/sale_return.xml',
        'views/sale_return_report.xml',
    ],

}
