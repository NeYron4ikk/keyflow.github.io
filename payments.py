# payments.py — заглушки для будущей интеграции платёжных систем
# Крипта и карты будут добавлены позже


class CryptoBotPayment:
    def __init__(self, token=""):
        self.token = token

    async def create_invoice(self, amount, order_id, description=""):
        raise NotImplementedError("CryptoBot будет добавлен позже")

    async def check_invoice(self, invoice_id):
        raise NotImplementedError("CryptoBot будет добавлен позже")


class SBPPayment:
    """СБП — ручная верификация через админа"""
    pass


class YooKassaPayment:
    def __init__(self, shop_id="", secret_key=""):
        self.shop_id    = shop_id
        self.secret_key = secret_key

    async def create_payment(self, amount, order_id, return_url=""):
        raise NotImplementedError("ЮКасса будет добавлена позже")

    async def check_payment(self, payment_id):
        raise NotImplementedError("ЮКасса будет добавлена позже")
