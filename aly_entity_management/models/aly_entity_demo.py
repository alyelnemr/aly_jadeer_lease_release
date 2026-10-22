import base64
import io
import math

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models


class AlyEntityDemo(models.AbstractModel):
    """Builds the demo scenarios through the real business flow (confirm, contract, sign,
    approve, invoice, pay, maintenance), so every case and state exists with consistent
    invoices, signatures and history. Only called from the demo data."""
    _name = 'aly.entity.demo'
    _description = 'Real Estate Demo Scenarios'


    @api.model
    def _ref(self, xmlid):
        return self.env.ref(f'aly_entity_management.{xmlid}')

    @api.model
    def _signature(self, name):
        """A hand-drawn looking signature image (PNG, base64)."""
        from PIL import Image, ImageDraw
        img = Image.new('RGBA', (420, 140), (255, 255, 255, 0))
        draw = ImageDraw.Draw(img)
        seed = sum(map(ord, name))
        points = []
        for step in range(0, 360):
            x = 20 + step
            y = 75 + 28 * math.sin((step + seed) / 17.0) * math.cos((step - seed) / 41.0)
            points.append((x, y))
        draw.line(points, fill=(20, 30, 90, 255), width=4, joint='curve')
        draw.line([(40, 115), (380, 108)], fill=(20, 30, 90, 255), width=2)
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        return base64.b64encode(buffer.getvalue())

    @api.model
    def _reservation(self, partner, unit, start, months=12, contract_type='lease', **vals):
        values = {
            'partner_id': self._ref(partner).id,
            'unit_id': self._ref(unit).id,
            'contract_type': contract_type,
            'date_start': start,
            'date_end': start + relativedelta(months=months, days=-1) if contract_type == 'lease' else False,
        }
        values.update(vals)
        return self.env['aly.entity.reservation'].create(values)

    @api.model
    def _contract(self, reservation, stage, via='office', **terms):
        """Take a confirmed reservation to the contract ``stage``:
        draft, awaiting_signature, signed or approved."""
        reservation.action_create_contract()
        contract = reservation.contract_id
        if terms:
            contract.write(terms)
        if stage == 'draft':
            return contract
        contract.action_send_for_signature()
        if stage == 'awaiting_signature':
            return contract
        name = reservation.partner_id.name
        contract._aly_sign(name, self._signature(name), via)
        if stage == 'signed':
            return contract
        contract.action_approve()
        contract.approved_by_id = self._ref('user_aly_khalid')
        return contract

    @api.model
    def _deal(self, partner, unit, start, months=12, contract_type='lease', stage='approved', via='office', **terms):
        reservation = self._reservation(partner, unit, start, months, contract_type)
        reservation.action_confirm()
        return self._contract(reservation, stage, via, **terms)

    @api.model
    def _installments(self, contract):
        return contract.invoice_ids.sorted('aly_installment_number')

    @api.model
    def _post(self, invoices):
        invoices.filtered(lambda m: m.state == 'draft').action_post()

    @api.model
    def _pay(self, invoice, amount=None, days_ago=0):
        self._post(invoice)
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids,
        ).create({'payment_date': fields.Date.context_today(self) - relativedelta(days=days_ago)})
        if amount:
            wizard.amount = amount
        wizard._create_payments()

    @api.model
    def _maintenance(self, unit, title, lines, request_date=None):
        employee_user = self._ref('user_aly_salem')
        request = self.env['aly.entity.maintenance.request'].with_user(employee_user).create({
            'title': title,
            'unit_id': self._ref(unit).id,
            'request_date': request_date or min(line['date'] for line in lines),
        })
        for line in lines:
            values = dict(line, request_id=request.id, employee_id=self._ref(line['employee_id']).id)
            self.env['aly.entity.maintenance.request.line'].with_user(employee_user).create(values)
        return request


    @api.model
    def _aly_load_demo_scenarios(self):
        today = fields.Date.context_today(self)
        M = lambda n: relativedelta(months=n)  # noqa: E731
        D = lambda n: relativedelta(days=n)  # noqa: E731

        for xmlid in ('contract_aly_ahmed_a101', 'contract_aly_mona_v02'):
            contract = self._ref(xmlid)
            contract.signature = self._signature(contract.partner_id.name)

        omar = self._deal('partner_aly_omar', 'unit_aly_a202', today - M(6), payment_frequency='monthly')
        invoices = self._installments(omar)
        for index, invoice in enumerate(invoices[:4]):
            self._pay(invoice, days_ago=(6 - index) * 30)
        self._pay(invoices[4], amount=2000, days_ago=40)
        self._post(invoices[5])

        layla = self._deal('partner_aly_layla', 'unit_aly_a302', today - M(14), months=24,
                           payment_frequency='annual')
        self._pay(self._installments(layla)[0], days_ago=420)

        john = self._deal('partner_aly_john', 'unit_aly_g02', today - M(1), payment_frequency='upfront')
        self._pay(self._installments(john), days_ago=30)

        self._deal('partner_aly_noura', 'unit_aly_a601', today + D(2), months=5, payment_frequency='quarterly')

        hassan = self._deal('partner_aly_hassan', 'unit_aly_o202', today - M(8), payment_frequency='semi_annual')
        invoices = self._installments(hassan)
        self._pay(invoices[0], days_ago=240)
        self._post(invoices[1])

        fatima = self._deal('partner_aly_fatima', 'unit_aly_w01', today - M(14), payment_frequency='quarterly')
        for index, invoice in enumerate(self._installments(fatima)):
            self._pay(invoice, days_ago=420 - index * 90)

        self._deal('partner_aly_khaled', 'unit_aly_w03', today + M(3), payment_frequency='annual')

        reem_sale = self._deal('partner_aly_reem', 'unit_aly_a501', today - M(1), contract_type='sale',
                               payment_frequency='upfront', service_fee=5000, admin_fee=1500)
        self._pay(self._installments(reem_sale), days_ago=25)

        khaled_lease = self._deal('partner_aly_khaled', 'unit_aly_v04', today - M(10), payment_frequency='quarterly')
        for invoice in self._installments(khaled_lease)[:3]:
            self._pay(invoice)
        self._deal('partner_aly_reem', 'unit_aly_v04', khaled_lease.date_end + D(1), months=24,
                   contract_type='sale', payment_frequency='semi_annual', service_fee=8000, admin_fee=2000)

        self._deal('partner_aly_noura', 'unit_aly_w02', today + M(1), stage='signed', payment_frequency='quarterly')

        self._deal('partner_aly_layla', 'unit_aly_a401', today + M(1), contract_type='sale', stage='awaiting_signature',
                   payment_frequency='semi_annual')

        self._deal('partner_aly_omar', 'unit_aly_o301', today + M(1), stage='draft', payment_frequency='monthly')

        cancelled = self._deal('partner_aly_fatima', 'unit_aly_w04', today + M(1), stage='awaiting_signature')
        reason = 'The customer asked for a lower floor.'
        cancelled._aly_cancel(reason)
        cancelled.reservation_id._aly_cancel(reason)

        self._reservation('partner_aly_khaled', 'unit_aly_g01', today + M(1)).action_confirm()

        expiring = self._reservation('partner_aly_john', 'unit_aly_o201', today + M(1))
        expiring.action_confirm()
        expiring.expiry_date = today + D(1)

        expired = self._reservation('partner_aly_reem', 'unit_aly_a301', today + M(1))
        expired.action_confirm()
        expired.expiry_date = today - D(1)
        self.env['aly.entity.reservation']._cron_expire_reservations()

        self._reservation('partner_aly_noura', 'unit_aly_v01', today + M(2), contract_type='sale')

        self._reservation('partner_aly_fatima', 'unit_aly_a202', today + M(1))

        for partner in ('partner_aly_omar', 'partner_aly_john'):
            self._reservation(partner, 'unit_aly_v03', today + M(2)).action_confirm()

        self._ref('partner_aly_hassan').write({
            'aly_is_blacklisted': True,
            'aly_blacklist_reason': 'Second rent installment of O-202 is overdue.',
        })

        manager = self._ref('user_aly_khalid')
        approved = self._maintenance('unit_aly_a202', 'Kitchen sink leak', [
            {'employee_id': 'employee_aly_fahd', 'date': today - D(20), 'time_from': 8.0, 'time_to': 10.0,
             'description': 'Found a cracked pipe under the sink (recorded late).'},
            {'employee_id': 'employee_aly_omar', 'date': today - D(4), 'time_from': 14.0, 'time_to': 16.5,
             'description': 'Replaced the pipe and tested for leaks.'},
        ])
        approved.action_submit()
        approved.with_user(manager).action_approve()

        office = self._maintenance('unit_aly_o202', 'Office AC not cooling', [
            {'employee_id': 'employee_aly_omar', 'date': today - D(3), 'time_from': 9.0, 'time_to': 11.0,
             'description': 'Cleaned the filters and refilled the gas.'},
        ])
        office.action_submit()

        sent_back = self._maintenance('unit_aly_a302', 'Broken door lock', [
            {'employee_id': 'employee_aly_fahd', 'date': today - D(5), 'time_from': 15.0, 'time_to': 16.0,
             'description': 'Changed the lock.'},
        ])
        sent_back.action_submit()
        sent_back.with_user(manager)._aly_send_back('Please add the lock model and the cost of the parts.')

        self._maintenance('unit_aly_a501', 'Handover inspection', [
            {'employee_id': 'employee_aly_omar', 'date': today - D(1), 'time_from': 8.0, 'time_to': 9.0,
             'description': 'Checked electricity, water and AC before handover.'},
        ])

        move_out = self._maintenance('unit_aly_w01', 'Move-out inspection', [
            {'employee_id': 'employee_aly_fahd', 'date': today - M(2) - D(3), 'time_from': 10.0, 'time_to': 12.0,
             'description': 'Inspected the unit after the tenant left; repainted one wall (recorded late).'},
        ], request_date=today - M(2) - D(3))
        move_out.action_submit()
        move_out.with_user(manager).action_approve()

        self.env['aly.entity.unit']._cron_recompute_state()
        self.env['account.move']._cron_aly_invoice_reminders()
        return True
