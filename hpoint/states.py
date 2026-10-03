from aiogram.fsm.state import State, StatesGroup

class Registration(StatesGroup):
    name = State()

class HelpRequest(StatesGroup):
    what = State()
    place = State()
    time_needed = State()
    urgency = State()
    details = State()

class Review(StatesGroup):
    requester_review = State()
    helper_review = State()

class HelperSettings(StatesGroup):
    categories = State()


class Billing(StatesGroup):
    ad_text = State()
    commercial_title = State()
    commercial_amount = State()
