from odoo import api, fields, models
from odoo.exceptions import UserError

SUPPORTED_MODELS = ('aly.entity.reservation', 'aly.entity.contract', 'aly.entity.maintenance.request')


class AlyEntityCancelWizard(models.TransientModel):
    _name = 'aly.entity.cancel.wizard'
    _description = 'Real Estate Reason Wizard'

    res_model = fields.Char(
        string='Document Model',
        required=True,
        readonly=True,
        help='Technical name of the documents being cancelled or sent back.',
    )
    res_ids = fields.Json(
        string='Document IDs',
        readonly=True,
        help='Technical list of the documents being cancelled or sent back.',
    )
    is_send_back = fields.Boolean(
        string='Send Back',
        readonly=True,
        help='Technical: the reason is for sending maintenance hours back for correction, '
             'not for a cancellation.',
    )
    reason = fields.Text(
        string='Reason',
        required=True,
        help='Why the document is cancelled or sent back. Kept on the document and in '
             'its history.',
    )

    @api.model
    def _aly_open(self):
        model = self.env.context.get('active_model')
        if model not in SUPPORTED_MODELS:
            raise UserError(self.env._('This document cannot be cancelled from here.'))
        is_send_back = bool(self.env.context.get('aly_send_back'))
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Send Back') if is_send_back else self.env._('Cancel'),
            'res_model': self._name,
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_res_model': model,
                'default_res_ids': self.env.context.get('active_ids', []),
                'default_is_send_back': is_send_back,
            },
        }

    def action_confirm(self):
        self.ensure_one()
        if self.res_model not in SUPPORTED_MODELS:
            raise UserError(self.env._('This document cannot be cancelled from here.'))
        records = self.env[self.res_model].browse(self.res_ids or []).exists()
        if self.is_send_back:
            records._aly_send_back(self.reason)
        else:
            records._aly_cancel(self.reason)
        return {'type': 'ir.actions.act_window_close'}
