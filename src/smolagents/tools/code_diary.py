import json
from datetime import datetime

class CodeDiary:
    def __init__(self, diary_file="code_diary.json"):
        self.diary_file = diary_file
        try:
            with open(self.diary_file, "r") as file:
                json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            with open(self.diary_file, "w") as file:
                json.dump([], file)

    def add_entry(self, module, notes):
        entry = {"timestamp": datetime.utcnow().isoformat(), "module": module, "notes": notes}
        with open(self.diary_file, "r") as file:
            diary = json.load(file)
        diary.append(entry)
        with open(self.diary_file, "w") as file:
            json.dump(diary, file, indent=4)
