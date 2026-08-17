from aiogram.fsm.state import State, StatesGroup


class Reg(StatesGroup):
    full_name = State()
    phone = State()
    photo = State()


class ProductForm(StatesGroup):
    name = State()
    price = State()
    unit = State()
    photo = State()
    supplier = State()
    edit_price = State()
    edit_name = State()
    edit_photo = State()
    search = State()


class SupplierForm(StatesGroup):
    name = State()
    phone = State()


class CustomerForm(StatesGroup):
    name = State()
    phone = State()
    address = State()
    balance = State()
    photo = State()
    search = State()
    set_balance = State()
    payment = State()
    debt = State()
    photo_edit = State()


class SaleForm(StatesGroup):
    customer = State()
    product_search = State()
    qty = State()
    price = State()
    payment_method = State()
    paid = State()
    comment = State()


class OrderForm(StatesGroup):
    product_search = State()
    qty = State()
    needed_at = State()
    address = State()
    comment = State()


class OrderManage(StatesGroup):
    price = State()
    delivery_time = State()
    driver_time = State()


class StaffForm(StatesGroup):
    phone = State()
    full_name = State()


class PaymentMethodForm(StatesGroup):
    name = State()


class LoginForm(StatesGroup):
    phone = State()


class JoinForm(StatesGroup):
    full_name = State()
    phone = State()
    photo = State()
