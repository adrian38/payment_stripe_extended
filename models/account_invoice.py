# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _, SUPERUSER_ID
from odoo.tests import Form
from odoo.tools.float_utils import float_round

from datetime import date, timedelta


class AccountMove(models.Model):
    _inherit = 'account.move'

    has_complaint = fields.Boolean(default=False)
    complaint_description = fields.Text("Complaint detailed description")
    complaint_approved = fields.Boolean(default=False)

    def cliente_stripe_pay_invoice(self, payment_token_id):
        payment_token = self.env['payment.token'].browse(payment_token_id)
        action = self.action_invoice_register_payment()
        # .with_user(SUPERUSER_ID)
        payment_form = Form(self.env['account.payment'].with_context(
            action['context']), view='account.view_account_payment_invoice_form')
        payment_form._values['journal_id'] = payment_token.acquirer_id.journal_id.id
        for payment_method in payment_token.acquirer_id.journal_id.inbound_payment_method_ids:
            if payment_method.code == 'electronic':
                payment_form._values['payment_method_id'] = payment_method.id
                payment_form._values['payment_method_code'] = 'electronic'
        payment_form._values['payment_token_id'] = payment_token.id
        payment = payment_form.save()
        payment.post()

        sale_order = self.env['sale.order'].search([('name','ilike',self.invoice_origin)])
        sale_order.paidout = True
        
        return payment.payment_transaction_id.id

    def pay_vendor_invoice(self):
        payment_stripe = self.env['payment.acquirer'].search([('provider', '=', 'stripe')])
        purchase_order = self.env['purchase.order'].search([('name','ilike',self.invoice_origin)])
        
        client_invoices = self.env['account.move'].search([('invoice_origin','ilike',purchase_order.origin)])
        # pay vendor invoices including self 
        vendor_invoices = self.env['account.move'].search([('invoice_origin','ilike',purchase_order.name)])
        
        for client_invoice, vendor_invoice in zip(client_invoices, vendor_invoices):
            
            action = vendor_invoice.action_invoice_register_payment()
            payment_form = Form(vendor_invoice.env['account.payment'].with_context(action['context']), view='account.view_account_payment_invoice_form')
            payment = payment_form.save()
            payment.post()

            client_payment_transaction = vendor_invoice.env['payment.transaction'].search([('id','=',client_invoice.transaction_ids.id)])
            # stripe transfer
            s2s_data_transfer = {
                "amount": int(float_round(vendor_invoice.amount_total * 100, 2)),
                "currency": vendor_invoice.currency_id.name,
                "destination": vendor_invoice.partner_id.stripe_connect_account_id,
                "source_transaction": client_payment_transaction.stripe_payment_intent_charge_id,
                "transfer_group": client_payment_transaction.reference,
            }
            transfer = payment_stripe._stripe_request('transfers', s2s_data_transfer)
            
            # return transfer info
            if transfer.get('id'):
                return_transaction_info = {
                    'po_id': purchase_order.id,
                    'stripe_transfer_id': transfer.get('id')
                }
                self.env['bus.bus'].sendone(
                    self._cr.dbname + '_' + str(self.partner_id.id),
                    {'type': 'stripe_transfer_vendor_notification', 'action':'created', "transaction_info":return_transaction_info})
        
        purchase_order.finish = True

        self.env['bus.bus'].sendone(
                self._cr.dbname + '_' + str(purchase_order.partner_id.id),
                {'type': 'po_finished', 'action':'finished', "po_id":purchase_order.id})

        if purchase_order.partner_id.id == 7 :  
            partners = self.env['res.partner'].search([(1,'=',1)])
            for partner in partners :
                self.env['bus.bus'].sendone(
                    self._cr.dbname + '_' + str(partner.id),
                    {'type': 'promotion', 'action':'new', "po_id":purchase_order.id})

        sale_order = self.env['sale.order'].search([('name','ilike',purchase_order.origin)])
        
        sale_order.finish = True
        
        self.env['bus.bus'].sendone(
                    self._cr.dbname + '_' + str(sale_order.partner_id.id),
                    {'type': 'so_finished', 'action':'finished', "so_id":sale_order.id})
        
        return True   

    def write(self, values):
        payment_stripe = self.env['payment.acquirer'].search(
            [('provider', '=', 'stripe')])
        if values.get('complaint_approved') == True:
            
            sale_order = self.env['sale.order'].search([('name','ilike',self.invoice_origin)])
            purchase_order = self.env['purchase.order'].search([('origin','ilike',sale_order.name)])

            client_invoices = self.env['account.move'].search([('invoice_origin','ilike',self.invoice_origin)])

            for client_invoice in client_invoices:

                client_payment_transaction = client_invoice.env['payment.transaction'].search(
                    [('id', '=', client_invoice.transaction_ids.id)])

                if client_payment_transaction:
                    s2s_data_refound = {
                        "charge": client_payment_transaction.stripe_payment_intent_charge_id,
                    }
                    
                    refound = payment_stripe._stripe_request(
                        'refunds', s2s_data_refound)
                    
                    if refound.get('id'):
                        return_refound_info = {
                            'odoo_invoice_id': client_invoice.id,
                            'stripe_refound_id': refound.get('id')
                        }
                        self.env['bus.bus'].sendone(
                            self._cr.dbname + '_' + str(self.partner_id.id),
                            {'type': 'stripe_refound_client_notification', 'action': 'created', "refound_info": return_refound_info})
                
            purchase_order.finish = True
            sale_order.finish = True

            self.env['bus.bus'].sendone(
                self._cr.dbname + '_' + str(purchase_order.partner_id.id),
                {'type': 'po_finished', 'action':'finished', "po_id":purchase_order.id})
        
            self.env['bus.bus'].sendone(
                self._cr.dbname + '_' + str(sale_order.partner_id.id),
                {'type': 'so_finished', 'action':'finished', "so_id":sale_order.id})

        result = super(AccountMove, self).write(values)
        return result