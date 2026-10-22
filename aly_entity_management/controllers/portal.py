import binascii

from odoo import fields, http
from odoo.exceptions import AccessError, MissingError, UserError, ValidationError
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager

from ..models.aly_entity_unit import ACTIVE_RESERVATION_STATES

PAGE_SIZE = 12


class AlyEntityPortal(CustomerPortal):


    def _aly_partner_domain(self):
        partner = request.env.user.partner_id
        return [('partner_id', 'child_of', [partner.commercial_partner_id.id])]

    def _aly_my_units(self):
        Contract = request.env['aly.entity.contract']
        contracts = Contract.search(self._aly_partner_domain() + [('state', '=', 'approved')])
        reservations = request.env['aly.entity.reservation'].search(
            self._aly_partner_domain() + [('state', 'in', ACTIVE_RESERVATION_STATES)]
        )
        return contracts.unit_id | reservations.unit_id

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        Reservation = request.env['aly.entity.reservation']
        Contract = request.env['aly.entity.contract']
        if 'aly_reservation_count' in counters:
            values['aly_reservation_count'] = Reservation.search_count(self._aly_partner_domain()) \
                if Reservation.has_access('read') else 0
        if 'aly_contract_count' in counters:
            values['aly_contract_count'] = Contract.search_count(
                self._aly_partner_domain() + [('state', '!=', 'draft')]
            ) if Contract.has_access('read') else 0
        if 'aly_unit_count' in counters:
            values['aly_unit_count'] = len(self._aly_my_units()) if Contract.has_access('read') else 0
        return values


    @http.route(['/my/reservations', '/my/reservations/page/<int:page>'], type='http', auth='user', website=True)
    def portal_my_reservations(self, page=1, **kw):
        Reservation = request.env['aly.entity.reservation']
        domain = self._aly_partner_domain()
        pager = portal_pager(url='/my/reservations', total=Reservation.search_count(domain), page=page, step=PAGE_SIZE)
        reservations = Reservation.search(domain, limit=PAGE_SIZE, offset=pager['offset'])
        values = self._prepare_portal_layout_values()
        values.update({'reservations': reservations, 'pager': pager, 'page_name': 'aly_reservation',
                       'default_url': '/my/reservations'})
        return request.render('aly_entity_management.portal_my_reservations', values)

    @http.route(['/my/reservations/<int:reservation_id>'], type='http', auth='public', website=True)
    def portal_my_reservation(self, reservation_id, access_token=None, report_type=None, download=False, message=None, **kw):
        try:
            reservation_sudo = self._document_check_access('aly.entity.reservation', reservation_id, access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')
        if report_type in ('html', 'pdf', 'text'):
            return self._show_report(model=reservation_sudo, report_type=report_type,
                                     report_ref='aly_entity_management.action_report_aly_entity_reservation',
                                     download=download)
        values = self._get_page_view_values(reservation_sudo, access_token, {
            'reservation': reservation_sudo, 'page_name': 'aly_reservation', 'message': message,
        }, 'my_aly_reservations_history', False)
        return request.render('aly_entity_management.portal_my_reservation', values)


    @http.route(['/my/contracts', '/my/contracts/page/<int:page>'], type='http', auth='user', website=True)
    def portal_my_contracts(self, page=1, **kw):
        Contract = request.env['aly.entity.contract']
        domain = self._aly_partner_domain() + [('state', '!=', 'draft')]
        pager = portal_pager(url='/my/contracts', total=Contract.search_count(domain), page=page, step=PAGE_SIZE)
        contracts = Contract.search(domain, limit=PAGE_SIZE, offset=pager['offset'])
        values = self._prepare_portal_layout_values()
        values.update({'contracts': contracts, 'pager': pager, 'page_name': 'aly_contract',
                       'default_url': '/my/contracts'})
        return request.render('aly_entity_management.portal_my_contracts', values)

    @http.route(['/my/contracts/<int:contract_id>'], type='http', auth='public', website=True)
    def portal_my_contract(self, contract_id, access_token=None, report_type=None, download=False, message=None, **kw):
        try:
            contract_sudo = self._document_check_access('aly.entity.contract', contract_id, access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')
        if contract_sudo.state == 'draft':
            return request.redirect('/my')
        if report_type in ('html', 'pdf', 'text'):
            return self._show_report(model=contract_sudo, report_type=report_type,
                                     report_ref='aly_entity_management.action_report_aly_entity_contract',
                                     download=download)
        values = self._get_page_view_values(contract_sudo, access_token, {
            'contract': contract_sudo,
            'installments': contract_sudo._aly_get_installments(),
            'invoices': contract_sudo.invoice_ids.filtered(lambda m: m.state == 'posted'),
            'page_name': 'aly_contract',
            'message': message,
        }, 'my_aly_contracts_history', False)
        return request.render('aly_entity_management.portal_my_contract', values)

    @http.route(['/my/contracts/<int:contract_id>/sign'], type='json', auth='public')
    def portal_contract_sign(self, contract_id, access_token=None, name=None, signature=None):
        access_token = access_token or request.httprequest.args.get('access_token')
        try:
            contract_sudo = self._document_check_access('aly.entity.contract', contract_id, access_token)
        except (AccessError, MissingError):
            return {'error': request.env._('Invalid contract.')}
        if contract_sudo.state != 'awaiting_signature':
            return {'error': request.env._('This contract is not waiting for your signature.')}
        if not signature:
            return {'error': request.env._('The signature is missing.')}
        try:
            contract_sudo._aly_sign(name, signature, 'portal')
        except (TypeError, binascii.Error):
            return {'error': request.env._('Invalid signature data.')}
        except UserError as error:
            return {'error': str(error)}
        return {
            'force_refresh': True,
            'redirect_url': contract_sudo.get_portal_url(query_string='&message=signed'),
        }


    @http.route(['/my/units'], type='http', auth='user', website=True)
    def portal_my_units(self, **kw):
        values = self._prepare_portal_layout_values()
        values.update({'units': self._aly_my_units(), 'page_name': 'aly_unit'})
        return request.render('aly_entity_management.portal_my_units', values)

    @http.route(['/my/reserve', '/my/reserve/page/<int:page>'], type='http', auth='user', website=True)
    def portal_reserve_units(self, page=1, entity_id=None, unit_type=None, offer=None, **kw):
        Unit = request.env['aly.entity.unit']
        domain = []
        if entity_id and entity_id.isdigit():
            domain.append(('entity_id', '=', int(entity_id)))
        if unit_type in ('residential', 'commercial'):
            domain.append(('unit_type', '=', unit_type))
        if offer == 'rent':
            domain.append(('is_for_rent', '=', True))
        elif offer == 'sale':
            domain.append(('is_for_sale', '=', True))
        url_args = {k: v for k, v in {'entity_id': entity_id, 'unit_type': unit_type, 'offer': offer}.items() if v}
        pager = portal_pager(url='/my/reserve', url_args=url_args, total=Unit.search_count(domain),
                             page=page, step=PAGE_SIZE)
        units = Unit.search(domain, limit=PAGE_SIZE, offset=pager['offset'])
        values = self._prepare_portal_layout_values()
        values.update({
            'units': units,
            'entities': request.env['aly.entity'].search([]),
            'pager': pager,
            'page_name': 'aly_reserve',
            'filters': {'entity_id': entity_id or '', 'unit_type': unit_type or '', 'offer': offer or ''},
            'is_blacklisted': request.env.user.partner_id.commercial_partner_id.aly_is_blacklisted,
        })
        return request.render('aly_entity_management.portal_reserve_units', values)

    @http.route(['/my/reserve/<int:unit_id>'], type='http', auth='user', methods=['GET', 'POST'], website=True)
    def portal_reserve_unit(self, unit_id, **post):
        unit = request.env['aly.entity.unit'].browse(unit_id).exists()
        if not unit:
            return request.redirect('/my/reserve')
        try:
            unit.check_access('read')
        except AccessError:
            return request.redirect('/my/reserve')
        partner = request.env.user.partner_id
        error = None
        if request.httprequest.method == 'POST':
            try:
                reservation = self._aly_create_portal_reservation(unit, partner, post)
                return request.redirect(f'/my/reservations/{reservation.id}?message=requested')
            except (UserError, ValidationError, ValueError) as exc:
                error = str(exc.args[0]) if exc.args else str(exc)
        values = self._prepare_portal_layout_values()
        values.update({
            'unit': unit,
            'page_name': 'aly_reserve',
            'error': error,
            'post': post,
            'is_blacklisted': partner.commercial_partner_id.aly_is_blacklisted,
        })
        return request.render('aly_entity_management.portal_reserve_unit', values)

    def _aly_create_portal_reservation(self, unit, partner, post):
        contract_type = post.get('contract_type')
        if contract_type not in ('lease', 'sale'):
            raise UserError(request.env._('Choose whether you want to rent or buy the unit.'))
        date_start = fields.Date.to_date(post.get('date_start') or None)
        date_end = fields.Date.to_date(post.get('date_end') or None) if contract_type == 'lease' else False
        if not date_start:
            raise UserError(request.env._('Choose the start (or handover) date.'))
        if date_start < fields.Date.context_today(unit):
            raise UserError(request.env._('The start date cannot be in the past.'))
        if contract_type == 'lease' and (not date_end or date_end <= date_start):
            raise UserError(request.env._('Choose an end date after the start date.'))
        partner.commercial_partner_id._aly_check_not_blacklisted()
        conflict = unit.sudo()._aly_get_conflict(contract_type, date_start, date_end or date_start)
        if conflict:
            raise UserError(conflict)
        reservation = request.env['aly.entity.reservation'].sudo().create({
            'partner_id': partner.id,
            'unit_id': unit.id,
            'contract_type': contract_type,
            'date_start': date_start,
            'date_end': date_end,
            'is_portal_request': True,
        })
        manager_user = reservation.manager_user_id
        if manager_user:
            reservation.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=request.env._('New portal reservation to confirm'),
                user_id=manager_user.id,
            )
        reservation.message_post(
            body=request.env._('Reservation requested by the customer from the portal.'),
            author_id=partner.id,
        )
        return reservation
