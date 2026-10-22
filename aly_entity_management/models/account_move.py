from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _name = 'account.move'
    _inherit = ['account.move', 'aly.entity.navigation.mixin']

    aly_contract_id = fields.Many2one(
        comodel_name='aly.entity.contract',
        string='Real Estate Contract',
        readonly=True,
        copy=False,
        index='btree_not_null',
        ondelete='restrict',
        help='Lease or sale contract that generated this invoice. A contract with '
             'invoices cannot be deleted.',
    )
    aly_installment_number = fields.Integer(
        string='Payment Number',
        readonly=True,
        copy=False,
        help='Position of this invoice in the payment plan of the contract (1 = first). '
             'The first invoice also carries the service and administrative fees.',
    )
    aly_installment_count = fields.Integer(
        string='Number of Payments',
        related='aly_contract_id.payment_count',
        help='Total number of invoices in the payment plan of the contract.',
    )
    aly_period_start = fields.Date(
        string='Period Start',
        readonly=True,
        copy=False,
        help='First day of the period this invoice covers.',
    )
    aly_period_end = fields.Date(
        string='Period End',
        readonly=True,
        copy=False,
        help='Last day of the period this invoice covers.',
    )
    aly_send_date = fields.Date(
        string='Planned Send Date',
        readonly=True,
        copy=False,
        index='btree_not_null',
        help='Day the responsible employee should confirm and send this invoice, i.e. the '
             'start of its period. Drives the reminders and the colors of "Invoices to Send".',
    )
    aly_reminder_sent = fields.Boolean(
        string='Reminder Sent',
        readonly=True,
        copy=False,
        help='Technical flag so the property manager gets only one reminder per invoice.',
    )
    aly_due_status = fields.Selection(
        selection=[
            ('overdue', 'Overdue'),
            ('soon', 'Due Soon'),
            ('later', 'Later'),
            ('done', 'Sent'),
        ],
        string='Sending Status',
        compute='_compute_aly_due_status',
        store=False,
        help='Overdue: the planned send date has passed and the invoice is still a draft. '
             'Due Soon: within the reminder days. Later: not yet. Sent: already confirmed.',
    )
    aly_entity_id = fields.Many2one(
        comodel_name='aly.entity',
        string='Property',
        related='aly_contract_id.entity_id',
        help='Property of the contract, used to group the invoices to send.',
    )
    aly_reservation_id = fields.Many2one(
        comodel_name='aly.entity.reservation',
        string='Reservation',
        related='aly_contract_id.reservation_id',
        help='Reservation the contract of this invoice was created from.',
    )
    aly_unit_id = fields.Many2one(
        comodel_name='aly.entity.unit',
        string='Unit',
        related='aly_contract_id.unit_id',
        help='Unit of the contract that generated this invoice.',
    )

    @api.depends('state', 'aly_send_date', 'aly_contract_id')
    def _compute_aly_due_status(self):
        today = fields.Date.context_today(self)
        for move in self:
            if not move.aly_contract_id or not move.aly_send_date:
                move.aly_due_status = False
            elif move.state != 'draft':
                move.aly_due_status = 'done'
            elif move.aly_send_date < today:
                move.aly_due_status = 'overdue'
            elif move.aly_send_date <= today + timedelta(days=move.company_id.aly_invoice_reminder_days):
                move.aly_due_status = 'soon'
            else:
                move.aly_due_status = 'later'

    def unlink(self):
        if self.filtered(lambda m: m.aly_contract_id and m.aly_contract_id.state == 'approved'):
            raise UserError(self.env._('Invoices of an approved real estate contract cannot be deleted.'))
        return super().unlink()

    def action_aly_post_and_send(self):
        """Confirm contract invoices and e-mail them to the customer (visible in the portal)."""
        drafts = self.filtered(lambda m: m.state == 'draft')
        drafts.action_post()
        template = self.env.ref('account.email_template_edi_invoice', raise_if_not_found=False)
        for move in drafts:
            move._portal_ensure_token()
            move.activity_feedback(['mail.mail_activity_data_todo'])
            if template and move.partner_id.email:
                move.with_context(force_send=False).message_post_with_source(
                    template, subtype_xmlid='mail.mt_comment',
                )
        return True

    @api.model
    def _cron_aly_invoice_reminders(self):
        today = fields.Date.context_today(self)
        moves = self.search([
            ('aly_contract_id', '!=', False),
            ('state', '=', 'draft'),
            ('aly_reminder_sent', '=', False),
        ])
        for move in moves:
            lead = timedelta(days=move.company_id.aly_invoice_reminder_days)
            if move.aly_send_date - lead > today:
                continue
            manager_user = move.aly_contract_id.entity_id.manager_id.user_id
            if manager_user:
                move.activity_schedule(
                    'mail.mail_activity_data_todo',
                    date_deadline=move.aly_send_date,
                    summary=self.env._('Confirm and send invoice'),
                    note=self.env._(
                        'Confirm and send the invoice of %(contract)s, payment %(number)s of %(count)s, '
                        'planned for %(date)s.',
                        contract=move.aly_contract_id.name, number=move.aly_installment_number,
                        count=move.aly_installment_count, date=move.aly_send_date,
                    ),
                    user_id=manager_user.id,
                )
            move.aly_reminder_sent = True
