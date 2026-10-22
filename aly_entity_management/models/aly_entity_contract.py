import logging
import math

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import format_date

_logger = logging.getLogger(__name__)

MONTHS_PER_PERIOD = {
    'monthly': 1,
    'quarterly': 3,
    'semi_annual': 6,
    'annual': 12,
}

SIGNED_TERMS = (
    'date_start', 'duration_unit', 'duration_value', 'yearly_rent', 'sale_price',
    'payment_frequency', 'service_fee', 'admin_fee',
)


class AlyEntityContract(models.Model):
    _name = 'aly.entity.contract'
    _description = 'Real Estate Contract'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin', 'aly.entity.navigation.mixin']
    _order = 'create_date desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Reference',
        required=True,
        readonly=True,
        copy=False,
        default='/',
        index='trigram',
        help='Unique reference given by the system when the contract is created, e.g. '
             'CON/2027/0001. Printed on the contract and on every invoice.',
    )
    reservation_id = fields.Many2one(
        comodel_name='aly.entity.reservation',
        string='Reservation',
        required=True,
        readonly=True,
        index=True,
        check_company=True,
        ondelete='restrict',
        help='Confirmed reservation the contract was created from. Customer, unit and '
             'type come from it.',
    )
    contract_type = fields.Selection(
        string='Contract Type',
        related='reservation_id.contract_type',
        store=True,
        index=True,
        help='Lease: the customer rents the unit for the contract period. Sale: the '
             'customer buys the unit, paying the price in installments or upfront.',
    )
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Customer',
        related='reservation_id.partner_id',
        store=True,
        index=True,
        help='Tenant or buyer of the contract, taken from the reservation. Invoices are '
             'issued to this customer.',
    )
    unit_id = fields.Many2one(
        comodel_name='aly.entity.unit',
        string='Unit',
        related='reservation_id.unit_id',
        store=True,
        index=True,
        help='Unit leased or sold by the contract, taken from the reservation.',
    )
    entity_id = fields.Many2one(
        comodel_name='aly.entity',
        string='Property',
        related='reservation_id.entity_id',
        store=True,
        index=True,
        help='Property of the unit, used to search and group contracts.',
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        related='reservation_id.company_id',
        store=True,
        index=True,
        help='Company that issues the contract and its invoices.',
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        related='company_id.currency_id',
        help='Currency of all the amounts of the contract.',
    )
    date_start = fields.Date(
        string='Start / Handover Date',
        required=True,
        tracking=True,
        help='Lease: first day of the rental period, and date of the first invoice. '
             'Sale: day the unit is handed over, and date of the first installment.',
    )
    duration_unit = fields.Selection(
        selection=[
            ('month', 'Months'),
            ('year', 'Years'),
        ],
        string='Duration In',
        required=True,
        help='Unit of the duration typed next to it: "Months + 18" is 18 months, '
             '"Years + 2" is 24 months. For a sale, it is the installment period.',
    )
    duration_value = fields.Integer(
        string='Duration',
        required=True,
        help='How many months or years the contract runs (lease) or the installments '
             'are spread over (sale). Must be greater than zero.',
    )
    duration_months = fields.Integer(
        string='Duration (Months)',
        compute='_compute_duration_months',
        store=True,
        help='Duration converted to months; it drives the end date, the lease value '
             'and the number of invoices.',
    )
    date_end = fields.Date(
        string='End Date',
        compute='_compute_date_end',
        store=True,
        help='Last day of the contract period (lease) or of the installment plan (sale), '
             'computed from the start date and the duration.',
    )
    yearly_rent = fields.Monetary(
        string='Yearly Rent',
        currency_field='currency_id',
        tracking=True,
        help='Rent for one year, copied from the unit when the contract is created and '
             'adjustable before it is sent. Later changes on the unit do not affect it.',
    )
    sale_price = fields.Monetary(
        string='Sale Price',
        currency_field='currency_id',
        tracking=True,
        help='Agreed price of the unit, copied from the unit when the contract is created '
             'and adjustable before it is sent.',
    )
    payment_frequency = fields.Selection(
        selection=[
            ('monthly', 'Monthly'),
            ('quarterly', 'Quarterly'),
            ('semi_annual', 'Semi-Annual'),
            ('annual', 'Annual'),
            ('upfront', 'One Full Payment Upfront'),
        ],
        string='Payment Frequency',
        required=True,
        default='quarterly',
        tracking=True,
        help='How often the customer is invoiced. Each invoice is dated at the start of '
             'its period; when the duration is not a multiple of the period, the last '
             'invoice covers only the remaining months. Upfront means one invoice for '
             'the whole value on the start date.',
    )
    payment_count = fields.Integer(
        string='Number of Payments',
        compute='_compute_payment_count',
        store=False,
        help='How many invoices the contract will produce with this duration and '
             'payment frequency.',
    )
    service_fee = fields.Monetary(
        string='Service Fee',
        currency_field='currency_id',
        tracking=True,
        help='Fixed service fee, proposed from the company settings. Billed once, on the '
             'first invoice.',
    )
    admin_fee = fields.Monetary(
        string='Administrative Fee',
        currency_field='currency_id',
        tracking=True,
        help='Fixed administrative fee, proposed from the company settings. Billed once, '
             'on the first invoice.',
    )
    base_amount = fields.Monetary(
        string='Rent / Price Value',
        currency_field='currency_id',
        compute='_compute_amounts',
        store=True,
        help='Lease: yearly rent / 12 x duration in months, the rent of the whole period. '
             'Sale: the sale price.',
    )
    total_amount = fields.Monetary(
        string='Full Contract Value',
        currency_field='currency_id',
        compute='_compute_amounts',
        store=True,
        tracking=True,
        help='Full value of the contract: rent of the whole period (or sale price) plus '
             'the service fee and the administrative fee.',
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('awaiting_signature', 'Awaiting Signature'),
            ('signed', 'Signed'),
            ('approved', 'Approved'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        required=True,
        default='draft',
        copy=False,
        tracking=True,
        index=True,
        help='Draft: the employee prepares the terms. Awaiting Signature: sent to the '
             'customer, visible in the portal. Signed: the customer signed in the office '
             'or online. Approved: a manager approved it, the unit is leased or sold and '
             'all invoices were created as drafts. Cancelled: stopped before approval.',
    )
    invoice_ids = fields.One2many(
        comodel_name='account.move',
        inverse_name='aly_contract_id',
        string='Invoices',
        help='Invoices created when the contract was approved, one per payment period.',
    )
    invoice_count = fields.Integer(
        string='Invoice Count',
        compute='_compute_invoice_counts',
        store=False,
        help='Number of invoices of the contract.',
    )
    due_invoice_count = fields.Integer(
        string='Due Invoices',
        compute='_compute_invoice_counts',
        store=False,
        help='Draft invoices whose planned send date is today, overdue, or within the '
             'reminder days.',
    )
    received_payment_count = fields.Integer(
        string='Received Payments',
        compute='_compute_invoice_counts',
        store=False,
        help='Number of customer payments reconciled with the invoices of this contract.',
    )
    signature = fields.Image(
        string='Customer Signature',
        copy=False,
        attachment=True,
        max_width=1024,
        max_height=1024,
        help='Signature drawn by the customer, in the office or in the portal. Printed on '
             'the signed contract.',
    )
    signed_by = fields.Char(
        string='Signed By',
        copy=False,
        tracking=True,
        help='Name typed by the person who signed.',
    )
    signed_on = fields.Datetime(
        string='Signed On',
        copy=False,
        tracking=True,
        help='Date and time of the signature.',
    )
    signed_via = fields.Selection(
        selection=[
            ('office', 'In Office'),
            ('portal', 'Online (Portal)'),
        ],
        string='Signed Via',
        copy=False,
        tracking=True,
        help='Where the customer signed: on screen in the office, or online in the portal.',
    )
    signature_received_by_id = fields.Many2one(
        comodel_name='res.users',
        string='Signature Received By',
        copy=False,
        ondelete='set null',
        help='Employee who received the signature in the office. Empty for online signatures.',
    )
    signed_attachment_id = fields.Many2one(
        comodel_name='ir.attachment',
        string='Signed Contract PDF',
        readonly=True,
        copy=False,
        ondelete='set null',
        help='PDF of the contract generated at the moment of the signature, with the '
             'signature printed on it. Opened by the "Signed Contract" smart button.',
    )
    sent_on = fields.Datetime(
        string='Sent On',
        readonly=True,
        copy=False,
        help='When the contract was sent to the customer for signature.',
    )
    approved_by_id = fields.Many2one(
        comodel_name='res.users',
        string='Approved By',
        readonly=True,
        copy=False,
        ondelete='set null',
        help='Manager who approved the contract.',
    )
    approved_on = fields.Datetime(
        string='Approved On',
        readonly=True,
        copy=False,
        help='When the manager approved the contract.',
    )
    cancel_reason = fields.Text(
        string='Cancellation Reason',
        readonly=True,
        copy=False,
        tracking=True,
        help='Why the contract was cancelled before approval.',
    )
    is_period_ended = fields.Boolean(
        string='Period Ended',
        compute='_compute_is_period_ended',
        store=False,
        help='The lease period of this approved contract is over; the unit is no longer '
             'leased by it.',
    )
    partner_is_blacklisted = fields.Boolean(
        string='Customer Blacklisted',
        related='partner_id.aly_is_blacklisted',
        help='Shows a warning banner when the customer is blacklisted.',
    )
    partner_blacklist_reason = fields.Text(
        string='Customer Blacklist Reason',
        related='partner_id.aly_blacklist_reason',
        help='Reason the customer was blacklisted, shown in the warning banner.',
    )
    conflict_warning = fields.Char(
        string='Availability Warning',
        compute='_compute_conflict_warning',
        store=False,
        help='Shown when another approved contract already occupies this period; the '
             'contract cannot be approved then.',
    )

    _sql_constraints = [
        ('duration_positive',
         'CHECK(duration_value > 0)',
         'The contract duration must be greater than zero.'),
        ('fees_positive',
         'CHECK(service_fee >= 0 AND admin_fee >= 0)',
         'The fees cannot be negative.'),
    ]


    @api.depends('duration_unit', 'duration_value')
    def _compute_duration_months(self):
        for contract in self:
            factor = 12 if contract.duration_unit == 'year' else 1
            contract.duration_months = max(contract.duration_value, 0) * factor

    @api.depends('date_start', 'duration_months')
    def _compute_date_end(self):
        for contract in self:
            if contract.date_start and contract.duration_months:
                contract.date_end = contract.date_start + relativedelta(months=contract.duration_months, days=-1)
            else:
                contract.date_end = False

    @api.depends('duration_months', 'payment_frequency')
    def _compute_payment_count(self):
        for contract in self:
            contract.payment_count = len(contract._aly_get_periods())

    @api.depends('contract_type', 'yearly_rent', 'sale_price', 'duration_months', 'service_fee', 'admin_fee')
    def _compute_amounts(self):
        for contract in self:
            if contract.contract_type == 'sale':
                base = contract.sale_price
            else:
                base = contract.yearly_rent / 12.0 * contract.duration_months
            base = contract.currency_id.round(base) if contract.currency_id else base
            contract.base_amount = base
            contract.total_amount = base + contract.service_fee + contract.admin_fee

    @api.depends('invoice_ids.state', 'invoice_ids.aly_send_date')
    def _compute_invoice_counts(self):
        today = fields.Date.context_today(self)
        for contract in self:
            lead = relativedelta(days=contract.company_id.aly_invoice_reminder_days)
            contract.invoice_count = len(contract.invoice_ids)
            contract.received_payment_count = len(contract.invoice_ids.reconciled_payment_ids)
            contract.due_invoice_count = len(contract.invoice_ids.filtered(
                lambda m: m.state == 'draft' and m.aly_send_date and m.aly_send_date <= today + lead
            ))

    @api.depends('state', 'contract_type', 'date_end')
    def _compute_is_period_ended(self):
        today = fields.Date.context_today(self)
        for contract in self:
            contract.is_period_ended = (
                contract.state == 'approved'
                and contract.contract_type == 'lease'
                and bool(contract.date_end)
                and contract.date_end < today
            )

    @api.depends('state', 'unit_id', 'contract_type', 'date_start', 'date_end')
    def _compute_conflict_warning(self):
        for contract in self:
            warning = ''
            if contract.state in ('draft', 'awaiting_signature', 'signed') and contract.unit_id and contract.date_end:
                warning = contract.unit_id._aly_get_conflict(
                    contract.contract_type, contract.date_start, contract._aly_period_end(),
                    exclude_contract=contract,
                )
            contract.conflict_warning = warning


    @api.constrains('contract_type', 'yearly_rent', 'sale_price')
    def _check_amounts(self):
        for contract in self:
            if contract.contract_type == 'lease' and contract.yearly_rent <= 0:
                raise ValidationError(self.env._('The yearly rent of a lease contract must be greater than zero.'))
            if contract.contract_type == 'sale' and contract.sale_price <= 0:
                raise ValidationError(self.env._('The sale price of a sale contract must be greater than zero.'))

    @api.model
    def _aly_prepare_values_from_reservation(self, reservation):
        """Hook: default terms of a new contract, taken from its reservation, the unit
        and the company settings."""
        company = reservation.company_id
        months = 12
        if reservation.contract_type == 'lease' and reservation.date_end:
            span = relativedelta(reservation.date_end + relativedelta(days=1), reservation.date_start)
            months = max(span.years * 12 + span.months, 1)
        values = {
            'date_start': reservation.date_start,
            'yearly_rent': reservation.unit_id.yearly_rent,
            'sale_price': reservation.unit_id.sale_price,
            'service_fee': company.aly_default_service_fee,
            'admin_fee': company.aly_default_admin_fee,
        }
        if months % 12 == 0:
            values.update(duration_unit='year', duration_value=months // 12)
        else:
            values.update(duration_unit='month', duration_value=months)
        return values

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('aly.entity.contract') or '/'
            if vals.get('reservation_id'):
                reservation = self.env['aly.entity.reservation'].browse(vals['reservation_id'])
                for key, value in self._aly_prepare_values_from_reservation(reservation).items():
                    vals.setdefault(key, value)
        return super().create(vals_list)

    def write(self, vals):
        locked_terms = set(SIGNED_TERMS) & set(vals)
        if locked_terms and self.filtered(lambda c: c.state != 'draft'):
            raise UserError(self.env._(
                'The terms of a contract cannot be changed once it has been sent for signature. '
                'Set it back to draft first (only possible while it is not signed).'
            ))
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda c: c.state != 'draft'):
            raise UserError(self.env._('Only draft contracts can be deleted; cancel the others instead.'))
        return super().unlink()

    def _get_report_base_filename(self):
        self.ensure_one()
        return f'Contract {self.name}'

    def _compute_access_url(self):
        super()._compute_access_url()
        for contract in self:
            contract.access_url = f'/my/contracts/{contract.id}'


    def _aly_period_end(self):
        self.ensure_one()
        return self.date_end if self.contract_type == 'lease' else self.date_start

    def _aly_get_periods(self):
        """Split the contract into payment periods: list of (start, end, months).

        Each period starts at the start of its payment cycle; the last one covers
        only the remaining months when the duration is not a multiple of the cycle."""
        self.ensure_one()
        total = self.duration_months
        if total <= 0:
            return []
        step = total if self.payment_frequency == 'upfront' else MONTHS_PER_PERIOD.get(self.payment_frequency, 1)
        periods = []
        for index in range(math.ceil(total / step)):
            done = index * step
            months = min(step, total - done)
            start = self.date_start + relativedelta(months=done) if self.date_start else False
            end = start + relativedelta(months=months, days=-1) if start else False
            periods.append((start, end, months))
        return periods

    def _aly_get_installments(self):
        """Return one dict per invoice. Amounts are proportional to the months of the
        period; the last installment absorbs the rounding so the sum is exact."""
        self.ensure_one()
        periods = self._aly_get_periods()
        installments = []
        allocated = 0.0
        for number, (start, end, months) in enumerate(periods, start=1):
            if number == len(periods):
                amount = self.currency_id.round(self.base_amount - allocated)
            else:
                amount = self.currency_id.round(self.base_amount * months / self.duration_months)
            allocated += amount
            installments.append({
                'number': number,
                'date_start': start,
                'date_end': end,
                'months': months,
                'amount': amount,
            })
        return installments

    def _aly_prepare_invoice_line_vals(self, installment):
        self.ensure_one()
        company = self.company_id
        lang_dates = {
            'start': format_date(self.env, installment['date_start']),
            'end': format_date(self.env, installment['date_end']),
        }
        if self.contract_type == 'lease':
            product = company._aly_get_product('rent')
            label = self.env._(
                'Rent of %(unit)s from %(start)s to %(end)s',
                unit=self.unit_id.display_name, **lang_dates,
            )
        else:
            product = company._aly_get_product('sale')
            label = self.env._(
                'Installment %(number)s of %(count)s for unit %(unit)s',
                number=installment['number'], count=self.payment_count, unit=self.unit_id.display_name,
            )
        lines = [{'product_id': product.id, 'name': label, 'quantity': 1, 'price_unit': installment['amount']}]
        if installment['number'] == 1:
            if self.service_fee:
                fee_product = company._aly_get_product('service_fee')
                lines.append({'product_id': fee_product.id, 'name': fee_product.name,
                              'quantity': 1, 'price_unit': self.service_fee})
            if self.admin_fee:
                fee_product = company._aly_get_product('admin_fee')
                lines.append({'product_id': fee_product.id, 'name': fee_product.name,
                              'quantity': 1, 'price_unit': self.admin_fee})
        return lines

    def _aly_prepare_invoice_vals(self, installment):
        """Hook: values of one draft invoice of the contract."""
        self.ensure_one()
        return {
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'company_id': self.company_id.id,
            'currency_id': self.currency_id.id,
            'invoice_date': installment['date_start'],
            'invoice_date_due': installment['date_start'],
            'invoice_origin': self.name,
            'ref': self.env._('%(contract)s - payment %(number)s of %(count)s',
                              contract=self.name, number=installment['number'], count=self.payment_count),
            'aly_contract_id': self.id,
            'aly_installment_number': installment['number'],
            'aly_period_start': installment['date_start'],
            'aly_period_end': installment['date_end'],
            'aly_send_date': installment['date_start'],
            'invoice_line_ids': [fields.Command.create(line) for line in self._aly_prepare_invoice_line_vals(installment)],
        }

    def _aly_create_invoices(self):
        for contract in self:
            contract_lang = contract.with_context(lang=contract.partner_id.lang or contract.env.lang)
            vals_list = [contract_lang._aly_prepare_invoice_vals(inst) for inst in contract._aly_get_installments()]
            self.env['account.move'].with_company(contract.company_id).create(vals_list)

    def _aly_check_ready(self):
        for contract in self:
            contract.partner_id._aly_check_not_blacklisted()
            if not contract.date_end:
                raise UserError(self.env._('Set the start date and duration of %(name)s.', name=contract.name))
            contract.unit_id._aly_check_availability(
                contract.contract_type, contract.date_start, contract._aly_period_end(), exclude_contract=contract,
            )

    def _aly_sign(self, name, signature, via):
        """Record a customer signature (office wizard or portal) and attach the signed PDF."""
        self.ensure_one()
        if self.state != 'awaiting_signature':
            raise UserError(self.env._('Contract %(name)s is not waiting for a signature.', name=self.name))
        if not signature:
            raise UserError(self.env._('The signature is missing.'))
        self.write({
            'signature': signature,
            'signed_by': name,
            'signed_on': fields.Datetime.now(),
            'signed_via': via,
            'signature_received_by_id': self.env.user.id if via == 'office' else False,
            'state': 'signed',
        })
        self.reservation_id.state = 'signed'
        self.env.flush_all()
        attachments = []
        try:
            if self.env.registry.ready:
                pdf = self.env['ir.actions.report'].sudo()._render_qweb_pdf(
                    'aly_entity_management.action_report_aly_entity_contract', self.ids,
                )[0]
                attachments.append((f'{self.name.replace("/", "_")}_signed.pdf', pdf))
        except UserError:
            _logger.warning('Could not render the signed PDF of contract %s', self.name)
        message = self.message_post(
            body=self.env._('Contract signed by %(name)s (%(via)s).',
                            name=name, via=dict(self._fields['signed_via'].selection)[via]),
            attachments=attachments,
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )
        self.signed_attachment_id = message.attachment_ids[:1]
        if self.reservation_id.manager_user_id:
            self.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=self.env._('Contract signed, waiting for manager approval'),
                user_id=self.reservation_id.manager_user_id.id,
            )

    def _aly_cancel(self, reason):
        if self.filtered(lambda c: c.state == 'approved'):
            raise UserError(self.env._('An approved contract cannot be cancelled.'))
        self.write({'state': 'cancelled', 'cancel_reason': reason})
        self.activity_unlink(['mail.mail_activity_data_todo'])
        if not self.env.context.get('aly_from_reservation'):
            reservations = self.reservation_id.filtered(lambda r: r.state in ('awaiting_signature', 'signed'))
            reservations.write({'state': 'confirmed'})

    def _aly_warn_overlapping_reservations(self):
        """Post a warning on other customers' reservations that the approval now blocks."""
        for contract in self:
            others = contract.unit_id.reservation_ids.filtered(
                lambda r: r.state in ('draft', 'confirmed', 'awaiting_signature', 'signed')
                and r != contract.reservation_id
            )
            for reservation in others:
                if reservation.unit_id._aly_get_conflict(
                        reservation.contract_type, reservation.date_start, reservation._aly_period_end()):
                    reservation.message_post(body=self.env._(
                        'Warning: contract %(contract)s was approved for this unit and overlaps this '
                        'reservation. Contact the customer before going further.',
                        contract=contract.name,
                    ))


    def action_send_for_signature(self):
        template = self.env.ref('aly_entity_management.mail_template_contract_signature', raise_if_not_found=False)
        for contract in self:
            if contract.state != 'draft':
                raise UserError(self.env._('Only draft contracts can be sent for signature.'))
            contract._aly_check_ready()
            contract._portal_ensure_token()
            contract.write({'state': 'awaiting_signature', 'sent_on': fields.Datetime.now()})
            contract.reservation_id.state = 'awaiting_signature'
            contract.message_subscribe(partner_ids=contract.partner_id.ids)
            if template:
                contract.message_post_with_source(template, subtype_xmlid='mail.mt_comment')
        return True

    def action_back_to_draft(self):
        for contract in self:
            if contract.state != 'awaiting_signature':
                raise UserError(self.env._('Only a contract waiting for signature can go back to draft.'))
            contract.state = 'draft'
            contract.reservation_id.state = 'confirmed'
        return True

    def action_sign_in_office(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Customer Signature'),
            'res_model': 'aly.entity.contract.sign.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_contract_id': self.id, 'default_signed_by': self.partner_id.name},
        }

    def action_approve(self):
        if not self.env.user.has_group('aly_entity_management.group_aly_entity_manager'):
            raise AccessError(self.env._('Only real estate managers can approve contracts.'))
        for contract in self:
            if contract.state != 'signed':
                raise UserError(self.env._('Only contracts signed by the customer can be approved.'))
            contract._aly_check_ready()
            contract.write({
                'state': 'approved',
                'approved_by_id': self.env.user.id,
                'approved_on': fields.Datetime.now(),
            })
            contract.reservation_id.state = 'contracted'
            contract.activity_feedback(['mail.mail_activity_data_todo'])
        self._aly_create_invoices()
        self._aly_warn_overlapping_reservations()
        return True

    def action_cancel(self):
        self.ensure_one()
        return self.env['aly.entity.cancel.wizard'].with_context(
            active_model=self._name, active_ids=self.ids,
        )._aly_open()

    def action_view_signed_contract(self):
        """Open the PDF signed by the customer; print it again when none was stored."""
        self.ensure_one()
        if self.signed_attachment_id:
            return {
                'type': 'ir.actions.act_url',
                'url': f'/web/content/{self.signed_attachment_id.id}',
                'target': 'new',
            }
        return self.action_print()

    def action_print(self):
        self.ensure_one()
        return self.env.ref('aly_entity_management.action_report_aly_entity_contract').report_action(self)

    def action_view_invoices(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('aly_entity_management.aly_entity_contract_invoice_action')
        action['domain'] = [('aly_contract_id', '=', self.id)]
        action['context'] = {'create': False}
        return action

    def action_view_payments(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('account.action_account_payments')
        action['domain'] = [('id', 'in', self.invoice_ids.reconciled_payment_ids.ids)]
        action['context'] = {'create': False}
        return action

    def action_view_due_invoices(self):
        self.ensure_one()
        action = self.action_view_invoices()
        action['context'] = {'create': False, 'search_default_filter_due': 1}
        return action

    @api.model
    def _aly_action_signatures(self, domain):
        action = self.env['ir.actions.act_window']._for_xml_id(
            'aly_entity_management.aly_entity_contract_signature_action')
        action['domain'] = domain + [('signed_on', '!=', False)]
        return action

    def action_view_maintenance(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'aly_entity_management.aly_entity_maintenance_request_action')
        action['domain'] = [('contract_id', '=', self.id)]
        action['context'] = {'default_unit_id': self.unit_id.id, 'default_contract_id': self.id}
        return action
