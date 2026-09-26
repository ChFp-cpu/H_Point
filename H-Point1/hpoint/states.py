from aiogram.fsm.state import State, StatesGroup
class Registration(StatesGroup):
    name=State(); skills=State(); portfolio=State()
class HelpRequest(StatesGroup):
    what=State(); place=State(); time_needed=State(); urgency=State(); details=State(); required_skills=State()
class ProfileEdit(StatesGroup):
    skills=State(); portfolio=State()
