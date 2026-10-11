"""The customer inbox: WhatsApp chats and order confirmations (ADR 0059).

- ``meta``: the only code that talks to WhatsApp.
- ``connection``: the WhatsApp keys and the second Shopify connection, saved
  from Settings.
- ``sending``: who may be messaged, and how a phone number is read.
"""
