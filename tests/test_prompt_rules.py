import unittest

from vialibera import agent, landing_chat


class PromptRules(unittest.TestCase):
    def test_italian_register_is_formal_in_both_chats(self):
        for text in (landing_chat._SYSTEM_TEMPLATE, agent.SYSTEM):
            self.assertIn('"Lei" (never "tu")', text)
            self.assertIn("never \"cibo\"", text)

    def test_the_page_announces_a_missing_list_so_the_chat_must_not_repeat_it(self):
        self.assertIn("never tell the visitor that a product or a route is", landing_chat._SYSTEM_TEMPLATE.lower().replace("\n", " "))
        self.assertTrue(landing_chat.NO_LIST["en"].startswith("MioTEM has no checked list"))


if __name__ == "__main__":
    unittest.main()
