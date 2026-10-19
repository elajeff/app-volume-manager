import unittest

from app_volume_manager.process_identity import identify_process_role


class ProcessIdentityTests(unittest.TestCase):
    def test_main_renderer_and_audio_utility_are_distinguishable(self):
        main = identify_process_role(r"C:\Discord\Discord.exe", [r"C:\Discord\Discord.exe"])
        renderer = identify_process_role(
            r"C:\Discord\Discord.exe",
            [r"C:\Discord\Discord.exe", "--type=renderer", "--renderer-client-id=41"],
        )
        utility = identify_process_role(
            "Discord.exe", ["Discord.exe", "--type=utility", "--utility-sub-type=audio.mojom.AudioService"]
        )
        self.assertEqual((main[1], renderer[1]), ("Main process", "Renderer process"))
        renderer_again = identify_process_role(
            "Discord.exe", ["Discord.exe", "--type=renderer", "--renderer-client-id=987"]
        )
        self.assertNotEqual(main[0], renderer[0])
        self.assertEqual(renderer[0], renderer_again[0])
        self.assertIn("subtype=audio.mojom.audioservice", utility[0])
        self.assertEqual(utility[1], "Utility: audio.mojom.audioservice")

    def test_ambiguous_or_unavailable_command_lines_are_not_saved_as_a_profile(self):
        for name, command_line in (
            ("someapp.exe", ["someapp.exe", "--private-job-id", "abc"]),
            ("Discord.exe", None),
        ):
            with self.subTest(command_line=command_line):
                signature, role = identify_process_role(name, command_line)
                self.assertIsNone(signature)
                self.assertTrue(role)


if __name__ == "__main__":
    unittest.main()
