# -*- coding: utf-8 -*-
# from odoo import http


# class SalePurchaseExtended(http.Controller):
#     @http.route('/sale_purchase_extended/sale_purchase_extended/', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/sale_purchase_extended/sale_purchase_extended/objects/', auth='public')
#     def list(self, **kw):
#         return http.request.render('sale_purchase_extended.listing', {
#             'root': '/sale_purchase_extended/sale_purchase_extended',
#             'objects': http.request.env['sale_purchase_extended.sale_purchase_extended'].search([]),
#         })

#     @http.route('/sale_purchase_extended/sale_purchase_extended/objects/<model("sale_purchase_extended.sale_purchase_extended"):obj>/', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('sale_purchase_extended.object', {
#             'object': obj
#         })
