# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
import requests
import pprint
from requests.exceptions import HTTPError
from werkzeug import urls

from odoo import api, fields, models, _
from odoo.tools.float_utils import float_round

from odoo.addons.payment.models.payment_acquirer import ValidationError
from odoo.addons.payment_stripe.controllers.main import StripeController

_logger = logging.getLogger(__name__)

# The following currencies are integer only, see https://stripe.com/docs/currencies#zero-decimal
INT_CURRENCIES = [
    u'BIF', u'XAF', u'XPF', u'CLP', u'KMF', u'DJF', u'GNF', u'JPY', u'MGA', u'PYG', u'RWF', u'KRW',
    u'VUV', u'VND', u'XOF'
]

class PaymentAcquirerStripe(models.Model):
    _inherit = 'payment.acquirer'

    def stripe_token_from_payment(self, data):
        # create payment_method
        s2s_data_payment_method = {
            'type': 'card',
            'card[number]': data.get('number'),
            'card[cvc]': data.get('cvc'),
            'card[exp_month]': data.get('exp_month'),
            'card[exp_year]': data.get('exp_year'),
        }
        payment_method = self._stripe_request('payment_methods', s2s_data_payment_method)

        # create customer
        s2s_data_customer = {
            'name': self.env.user.partner_id.name,
            'email': self.env.user.partner_id.email
        }
        customer = self._stripe_request('customers', s2s_data_customer)

        # link customer with payment method
        api_url_payment_method = 'payment_methods/%s/attach' % payment_method.get('id')
        method_data = {
            'customer': customer.get('id')
        }
        self._stripe_request(api_url_payment_method, method_data)
        
        # create payment.token
        if customer.get('id') and payment_method.get('id'):
            s2s_data_token = {
                'customer': customer.get('id'),
                'payment_method': payment_method.get('id'),
                'card': payment_method.get('card'),
                'acquirer_id': self.id,
                'partner_id': self.env.user.partner_id.id
            }
            token = self.stripe_s2s_form_process(s2s_data_token)
            return token.id
        else:
            return False
    
    def stripe_transfer(self, data):
        # create transfer object
        s2s_data_transfer = {
            "amount": data.get('amount'),
            "currency": data.get('currency'),
            "source_transaction": data.get('charge_id'),
            "destination": data.get('account_id')
        }
        transfer = self._stripe_request('transfers', s2s_data_transfer)
        # return transfer id
        if transfer.get('id'):
            self.env['bus.bus'].sendone(
                self._cr.dbname + '_' + str(self.id),
                {'type': 'stripe_transfer_vendor_notification', 'action':'created', "account_id":transfer.get('id')})
            return transfer.get('id')
        else:
            return False

class PaymentTransactionStripe(models.Model):
    _inherit = 'payment.transaction'

    stripe_payment_intent_charge_id = fields.Char(string='Stripe Payment Intent Charge ID')

    # the same as the original method just adding transfer_group property to link futures payouts to vendors
    def _stripe_create_payment_intent(self, acquirer_ref=None, email=None):
        if not self.payment_token_id.stripe_payment_method:
            # old token before using sca, need to fetch data from the api
            self.payment_token_id._stripe_sca_migrate_customer()

        charge_params = {
            'amount': int(self.amount if self.currency_id.name in INT_CURRENCIES else float_round(self.amount * 100, 2)),
            'currency': self.currency_id.name.lower(),
            'off_session': True,
            'confirm': True,
            'payment_method': self.payment_token_id.stripe_payment_method,
            'customer': self.payment_token_id.acquirer_ref,
            "description": self.reference,
            "transfer_group": self.reference, 
        }

        if not self.env.context.get('off_session'):
            charge_params.update(setup_future_usage='off_session', off_session=False)
        _logger.info('_stripe_create_payment_intent: Sending values to stripe, values:\n%s', pprint.pformat(charge_params))

        res = self.acquirer_id._stripe_request('payment_intents', charge_params)
        if res.get('charges') and res.get('charges').get('total_count'):
            res = res.get('charges').get('data')[0]
            self.stripe_payment_intent_charge_id = res.get('id')

        _logger.info('_stripe_create_payment_intent: Values received:\n%s', pprint.pformat(res))
        return res

    def _set_transaction_done(self):
        super(PaymentTransactionStripe, self)._set_transaction_done()
        self.env['bus.bus'].sendone(
            self._cr.dbname + '_' + str(self.partner_id.id),
            {'type': 'payment_transaction_notification', 'action':'successed', "transaction_id":self.id, "reference":self.reference, "amount":self.amount})
    
    def _set_transaction_cancel(self):
        super(PaymentTransactionStripe, self)._set_transaction_cancel()
        self.env['bus.bus'].sendone(
            self._cr.dbname + '_' + str(self.partner_id.id),
            {'type': 'payment_transaction_notification', 'action':'cancelled', "transaction_id":self.id, "reference":self.reference, "amount":self.amount})
    
    def _set_transaction_error(self, msg):
        super(PaymentTransactionStripe, self)._set_transaction_error(msg)
        self.env['bus.bus'].sendone(
            self._cr.dbname + '_' + str(self.partner_id.id),
            {'type': 'payment_transaction_notification', 'action':'error', "transaction_id":self.id, "reference":self.reference, "amount":self.amount, "message":self.state_message})