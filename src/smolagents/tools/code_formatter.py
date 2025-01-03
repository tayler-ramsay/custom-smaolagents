import black

class CodeFormatter:
    @staticmethod
    def suggest_refactoring(code):
        # A simple example of suggesting refactoring by checking for long lines
        suggestions = []
        lines = code.split('\n')
        for i, line in enumerate(lines):
            if len(line) > 80:
                suggestions.append(f"Line {i+1} is too long ({len(line)} characters). Consider breaking it into multiple lines.")
        return suggestions if suggestions else "No refactoring suggestions."

    def format_code(code):
        return black.format_str(code, mode=black.Mode())
