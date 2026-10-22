{
    'name': 'Real Estate Leasing and Sales',
    'version': '18.0.1.0.0',
    'category': 'Real Estate',
    'summary': 'Properties, units, reservations, lease and sale contracts, '
               'installment invoices, maintenance hours and a customer portal',
    'description': """
Real Estate Leasing and Sales
=============================
Takes a customer from registration, through a reservation and a signed contract,
to an approved contract and all its invoices, with a clear view of which units are
available, reserved, leased or sold.
    """,
    'author': 'Aly',
    'license': 'LGPL-3',
    'depends': [
        'mail',
        'portal',
        'hr',
        'account',
    ],
    'data': [
        'security/aly_entity_management_groups.xml',
        'security/ir.model.access.csv',
        'security/aly_entity_management_security.xml',
        'data/ir_sequence_data.xml',
        'data/product_data.xml',
        'data/mail_template_data.xml',
        'data/ir_cron_data.xml',
        'report/aly_entity_contract_report.xml',
        'report/aly_entity_reservation_report.xml',
        'report/aly_entity_contract_value_report_views.xml',
        'wizard/aly_entity_cancel_wizard_views.xml',
        'wizard/aly_entity_contract_sign_wizard_views.xml',
        'wizard/aly_entity_settings_wizard_views.xml',
        'views/res_partner_views.xml',
        'views/hr_employee_views.xml',
        'views/aly_entity_views.xml',
        'views/aly_entity_unit_views.xml',
        'views/aly_entity_reservation_views.xml',
        'views/aly_entity_contract_views.xml',
        'views/account_move_views.xml',
        'views/aly_entity_maintenance_request_views.xml',
        'views/aly_entity_management_menus.xml',
        'views/portal_templates.xml',
    ],
    'demo': [
        'demo/aly_entity_management_demo.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'aly_entity_management/static/src/scss/aly_entity_management.scss',
        ],
        'web.assets_frontend': [
            'aly_entity_management/static/src/scss/aly_entity_management.scss',
            'aly_entity_management/static/src/js/portal_reserve.js',
        ],
    },
    'application': True,
    'installable': True,
}
