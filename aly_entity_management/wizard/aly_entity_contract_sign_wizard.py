from odoo import fields, models


class AlyEntityContractSignWizard(models.TransientModel):
    _name = 'aly.entity.contract.sign.wizard'
    _description = 'Contract Signature in Office'

    contract_id = fields.Many2one(
        comodel_name='aly.entity.contract',
        string='Contract',
        required=True,
        readonly=True,
        ondelete='cascade',
        help='Contract the customer is signing.',
    )
    total_amount = fields.Monetary(
        string='Full Contract Value',
        related='contract_id.total_amount',
        currency_field='currency_id',
        help='Value the customer accepts by signing.',
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        related='contract_id.currency_id',
        help='Currency of the contract, used to display the value the customer accepts.',
    )
    signed_by = fields.Char(
        string='Signer Name',
        required=True,
        help='Full name of the person signing in front of the employee.',
    )
    signature = fields.Image(
        string='Signature',
        required=True,
        max_width=1024,
        max_height=1024,
        help='Signature drawn by the customer on the screen.',
    )

    def action_sign(self):
        self.ensure_one()
        self.contract_id._aly_sign(self.signed_by, self.signature, 'office')
        return {'type': 'ir.actions.act_window_close'}
