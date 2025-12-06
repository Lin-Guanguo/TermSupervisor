"""ContentCleaner 单元测试"""

from termsupervisor.analysis.content_cleaner import ContentCleaner


class TestIsAllowedChar:
    """测试字符白名单判断"""

    def test_english_letters(self):
        """英文字母应该通过"""
        for c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ":
            assert ContentCleaner.is_allowed_char(c), f"'{c}' should be allowed"

    def test_digits(self):
        """数字应该通过"""
        for c in "0123456789":
            assert ContentCleaner.is_allowed_char(c), f"'{c}' should be allowed"

    def test_chinese(self):
        """中文应该通过"""
        for c in "你好世界编译完成测试":
            assert ContentCleaner.is_allowed_char(c), f"'{c}' should be allowed"

    def test_japanese(self):
        """日语应该通过"""
        # 平假名
        for c in "あいうえおかきくけこ":
            assert ContentCleaner.is_allowed_char(c), f"'{c}' should be allowed"
        # 片假名
        for c in "アイウエオカキクケコ":
            assert ContentCleaner.is_allowed_char(c), f"'{c}' should be allowed"

    def test_korean(self):
        """韩语应该通过"""
        for c in "안녕하세요":
            assert ContentCleaner.is_allowed_char(c), f"'{c}' should be allowed"

    def test_accented_letters(self):
        """带重音的拉丁字母应该通过"""
        for c in "ÀÁÂÃÄÅàáâãäåÈÉÊËèéêëÎÏîï":
            assert ContentCleaner.is_allowed_char(c), f"'{c}' should be allowed"

    def test_space_not_allowed(self):
        """空格不应该通过"""
        assert not ContentCleaner.is_allowed_char(" ")
        assert not ContentCleaner.is_allowed_char("\t")
        assert not ContentCleaner.is_allowed_char("\n")

    def test_punctuation_not_allowed(self):
        """标点符号不应该通过"""
        for c in ",.!?;:'\"-_()[]{}@#$%^&*+=<>/\\|`~":
            assert not ContentCleaner.is_allowed_char(c), f"'{c}' should NOT be allowed"

    def test_chinese_punctuation_not_allowed(self):
        """中文标点不应该通过"""
        for c in "。、！？；：''（）【】《》":
            assert not ContentCleaner.is_allowed_char(c), f"'{c}' should NOT be allowed"

    def test_spinner_chars_not_allowed(self):
        """Spinner 字符不应该通过"""
        for c in "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏":
            assert not ContentCleaner.is_allowed_char(c), f"'{c}' should NOT be allowed"

    def test_progress_bar_chars_not_allowed(self):
        """进度条字符不应该通过"""
        for c in "█▓▒░▏▎▍▌▋▊▉":
            assert not ContentCleaner.is_allowed_char(c), f"'{c}' should NOT be allowed"

    def test_emoji_not_allowed(self):
        """Emoji 不应该通过"""
        for c in "😀🎉✓✗❌✅":
            assert not ContentCleaner.is_allowed_char(c), f"'{c}' should NOT be allowed"


class TestCleanLine:
    """测试单行清洗"""

    def test_remove_ansi(self):
        """移除 ANSI 转义序列"""
        line = "\x1b[32mGreen text\x1b[0m"
        assert ContentCleaner.clean_line(line) == "Greentext"

    def test_remove_spaces_and_punctuation(self):
        """移除空格和标点"""
        line = "Hello, World! This is a test."
        assert ContentCleaner.clean_line(line) == "HelloWorldThisisatest"

    def test_keep_chinese(self):
        """保留中文"""
        line = "编译完成，共 100 个文件。"
        assert ContentCleaner.clean_line(line) == "编译完成共100个文件"

    def test_spinner_progress_example(self):
        """Spinner 和进度条示例"""
        line = "Loading... ⠋ [50%] ████░░ Done!"
        assert ContentCleaner.clean_line(line) == "Loading50Done"

    def test_error_message(self):
        """错误消息"""
        line = "Error: file not found!"
        assert ContentCleaner.clean_line(line) == "Errorfilenotfound"

    def test_empty_line(self):
        """空行"""
        assert ContentCleaner.clean_line("") == ""
        assert ContentCleaner.clean_line("   ") == ""
        assert ContentCleaner.clean_line("---") == ""


class TestCleanContent:
    """测试整体内容清洗"""

    def test_multiline(self):
        """多行内容"""
        content = """Line 1: Hello
Line 2: World
Line 3: Test"""
        result = ContentCleaner.clean_content(content)
        assert result == ["Line1Hello", "Line2World", "Line3Test"]

    def test_skip_empty_lines(self):
        """跳过空行"""
        content = """Hello

World

"""
        result = ContentCleaner.clean_content(content)
        assert result == ["Hello", "World"]

    def test_skip_punctuation_only_lines(self):
        """跳过只有标点的行"""
        content = """Hello
---
World
==="""
        result = ContentCleaner.clean_content(content)
        assert result == ["Hello", "World"]


class TestCleanContentStr:
    """测试清洗后字符串输出"""

    def test_basic(self):
        """基本功能"""
        content = "Hello, World!\nTest 123"
        result = ContentCleaner.clean_content_str(content)
        assert result == "HelloWorld\nTest123"


class TestDiffLines:
    """测试行 diff"""

    def test_no_change(self):
        """无变化"""
        old = "Hello\nWorld"
        new = "Hello\nWorld"
        changed, details = ContentCleaner.diff_lines(old, new)
        assert changed == 0
        assert details == []

    def test_add_lines(self):
        """新增行"""
        old = "Hello"
        new = "Hello\nWorld"
        changed, details = ContentCleaner.diff_lines(old, new)
        assert changed == 1
        assert "+World" in details

    def test_remove_lines(self):
        """删除行"""
        old = "Hello\nWorld"
        new = "Hello"
        changed, details = ContentCleaner.diff_lines(old, new)
        assert changed == 1
        assert "-World" in details

    def test_change_lines(self):
        """修改行"""
        old = "Hello"
        new = "World"
        changed, details = ContentCleaner.diff_lines(old, new)
        assert changed == 2  # -Hello +World
        assert "-Hello" in details
        assert "+World" in details

    def test_same_text_different_punctuation(self):
        """相同文字不同标点应该无变化"""
        old = "Hello, World!"
        new = "Hello World"
        # 清洗后都是 "HelloWorld"
        cleaned_old = ContentCleaner.clean_content_str(old)
        cleaned_new = ContentCleaner.clean_content_str(new)
        changed, details = ContentCleaner.diff_lines(cleaned_old, cleaned_new)
        assert changed == 0

    def test_spinner_change_ignored(self):
        """Spinner 变化应该被忽略"""
        old = "Loading... ⠋"
        new = "Loading... ⠙"
        # 清洗后都是 "Loading"
        cleaned_old = ContentCleaner.clean_content_str(old)
        cleaned_new = ContentCleaner.clean_content_str(new)
        changed, details = ContentCleaner.diff_lines(cleaned_old, cleaned_new)
        assert changed == 0


class TestContentHash:
    """测试内容 hash"""

    def test_same_content_same_hash(self):
        """相同内容相同 hash"""
        content1 = "Hello World"
        content2 = "Hello World"
        assert ContentCleaner.content_hash(content1) == ContentCleaner.content_hash(content2)

    def test_different_content_different_hash(self):
        """不同内容不同 hash"""
        content1 = "Hello"
        content2 = "World"
        assert ContentCleaner.content_hash(content1) != ContentCleaner.content_hash(content2)

    def test_same_text_different_punctuation_same_hash(self):
        """相同文字不同标点相同 hash"""
        content1 = "Hello, World!"
        content2 = "Hello World"
        assert ContentCleaner.content_hash(content1) == ContentCleaner.content_hash(content2)

    def test_spinner_changes_same_hash(self):
        """Spinner 变化相同 hash"""
        content1 = "Loading... ⠋"
        content2 = "Loading... ⠙"
        assert ContentCleaner.content_hash(content1) == ContentCleaner.content_hash(content2)

    def test_progress_bar_changes_same_hash(self):
        """进度条变化相同 hash"""
        content1 = "Progress: [████░░░░░░] 40%"
        content2 = "Progress: [██████░░░░] 60%"
        # 清洗后都只保留 "Progress4060"（只有数字变了）
        # 注意：这里数字变了所以 hash 不同
        h1 = ContentCleaner.content_hash(content1)
        h2 = ContentCleaner.content_hash(content2)
        # 40 vs 60，不同
        assert h1 != h2

    def test_progress_bar_same_percent_same_hash(self):
        """相同百分比的进度条相同 hash"""
        content1 = "Progress: [████░░░░░░] 40%"
        content2 = "Progress: [====>     ] 40%"
        assert ContentCleaner.content_hash(content1) == ContentCleaner.content_hash(content2)
