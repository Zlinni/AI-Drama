import os
import openai
from dotenv import load_dotenv
from colorama import Fore, Style, init
import time
import re
import json
from datetime import datetime
import tiktoken
import keyboard
import sys

# 根据操作系统导入相应模块
if os.name == 'nt':
    import msvcrt
else:
    import tty
    import termios

# 初始化colorama
init()

# 加载环境变量
load_dotenv()

# 角色图标
ICONS = {
    "positive": "🔵",  # 正方
    "negative": "🔴",  # 反方
    "judge": "⚖️",    # 判官
    "system": "🔧",   # 系统消息
    "cursor": "➤"     # 选择光标
}

# 枚举 正方反方
CH = {
    "positive": "正方",
    "negative": "反方"
}

def stream_print(text, color=None, delay=0.03):
    """流式打印文本"""
    if color:
        sys.stdout.write(color)
    for char in text:
        sys.stdout.write(char)
        sys.stdout.flush()
        time.sleep(delay)
    if color:
        sys.stdout.write(Style.RESET_ALL)
    sys.stdout.write('\n')
    sys.stdout.flush()

class KeyboardHandler:
    def __init__(self):
        self.is_windows = os.name == 'nt'
        if not self.is_windows:
            self.old_settings = termios.tcgetattr(sys.stdin)

    def init_terminal(self):
        if not self.is_windows:
            tty.setraw(sys.stdin.fileno())

    def restore_terminal(self):
        if not self.is_windows:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old_settings)

    def get_key(self):
        if self.is_windows:
            key = msvcrt.getch()
            if key == b'\xe0':  # 特殊键的前缀
                key = msvcrt.getch()
                return {b'H': 'up', b'P': 'down'}.get(key, '')
            return {b'\r': 'enter'}.get(key, '')
        else:
            key = sys.stdin.read(1)
            if key == '\x1b':
                sys.stdin.read(1)
                key = sys.stdin.read(1)
                return {'A': 'up', 'B': 'down'}.get(key, '')
            return {'\n': 'enter'}.get(key, '')

def clear_lines(num_lines):
    """清除指定行数的内容"""
    if os.name == 'nt':
        os.system('cls')
    else:
        for _ in range(num_lines):
            sys.stdout.write('\033[F')  # 光标上移一行
            sys.stdout.write('\033[K')  # 清除该行

def display_menu(options, selected):
    """显示菜单并返回选择的选项"""
    for i, option in enumerate(options):
        if i == selected:
            print(f"{ICONS['cursor']} {Fore.CYAN}{option}{Style.RESET_ALL}")
        else:
            print(f"  {option}")

class AIModel:
    def __init__(self, api_key, api_base=None, model=None):
        self.client = openai.OpenAI(
            api_key=api_key,
            base_url=api_base or "https://api.openai.com/v1"
        )
        self.model = model or "gpt-3.5-turbo"
        self.encoding = tiktoken.encoding_for_model(self.model)

    def count_tokens(self, text):
        """计算文本的token数量"""
        return len(self.encoding.encode(text))

    def get_stream_response(self, messages, temperature=0.7, max_tokens=None):
        """获取流式响应"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True  # 启用流式输出
            )
            return response
        except Exception as e:
            print(f"{Fore.RED}Error: {str(e)}{Style.RESET_ALL}")
            return None

class DebateRecord:
    def __init__(self, topic, timestamp, debate_history, judge_analysis=None):
        self.topic = topic
        self.timestamp = timestamp
        self.debate_history = debate_history
        self.judge_analysis = judge_analysis

    @staticmethod
    def save_debate(topic, debate_history, judge_analysis=None):
        """保存辩论记录"""
        record = {
            "topic": topic,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "debate_history": debate_history,
            "judge_analysis": judge_analysis
        }
        
        # 确保存储目录存在
        os.makedirs("debates", exist_ok=True)
        
        # 生成文件名
        filename = f"debates/debate_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        # 保存记录
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        
        return filename

    @staticmethod
    def load_debates():
        """加载所有辩论记录"""
        debates = []
        if not os.path.exists("debates"):
            return debates
        
        for filename in os.listdir("debates"):
            if filename.endswith(".json"):
                with open(os.path.join("debates", filename), "r", encoding="utf-8") as f:
                    record = json.load(f)
                    debates.append(record)
        
        # 按时间戳排序
        debates.sort(key=lambda x: x["timestamp"], reverse=True)
        return debates

class AIDebate:
    def __init__(self):
        # 初始化正方模型
        positive_api_key = os.getenv("OPENAI_API_KEY_POSITIVE")
        positive_api_base = os.getenv("OPENAI_API_BASE_POSITIVE")
        positive_model = os.getenv("OPENAI_MODEL_POSITIVE", "gpt-3.5-turbo")
        self.positive_ai = AIModel(positive_api_key, positive_api_base, positive_model)

        # 初始化反方模型
        negative_api_key = os.getenv("OPENAI_API_KEY_NEGATIVE")
        negative_api_base = os.getenv("OPENAI_API_BASE_NEGATIVE")
        negative_model = os.getenv("OPENAI_MODEL_NEGATIVE", "gpt-3.5-turbo")
        self.negative_ai = AIModel(negative_api_key, negative_api_base, negative_model)

        # 初始化判官模型
        judge_api_key = os.getenv("OPENAI_API_KEY_JUDGE")
        judge_api_base = os.getenv("OPENAI_API_BASE_JUDGE")
        judge_model = os.getenv("OPENAI_MODEL_JUDGE", "gpt-3.5-turbo")
        self.judge_ai = AIModel(judge_api_key or positive_api_key, judge_api_base, judge_model)

        self.is_running = True
        self.debate_history = []

    def calculate_read_time(self, text):
        """计算阅读时间（秒）"""
        clean_text = re.sub(r'[^\w\s]', '', text)
        char_count = len(clean_text)
        read_time = char_count / 4
        return max(2, min(10, read_time))

    def get_ai_response(self, side, topic, context):
        """获取AI回应"""
        try:
            if side == "positive":
                ai_model = self.positive_ai
                prompt = f"你是这个话题的支持者。基于主题'{topic}'，请简短有力地支持该观点，回应对方的质疑。要求：\n1. 言简意赅\n2. 论点明确\n3. 基于对方的发言进行回应"
            else:
                ai_model = self.negative_ai
                prompt = f"你是这个话题的反对者。基于主题'{topic}'，请简短有力地反对该观点，回应对方的论述。要求：\n1. 言简意赅\n2. 论点明确\n3. 基于对方的发言进行回应"

            # 计算输入token
            input_tokens = ai_model.count_tokens(prompt + context)

            # 获取流式响应
            response_stream = ai_model.get_stream_response(
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": context}
                ],
            )
            
            if not response_stream:
                return None, 0

            # 准备接收完整响应
            full_response = ""
            
            # 流式输出响应
            icon = ICONS['positive'] if side == "positive" else ICONS['negative']
            color = Fore.BLUE if side == "positive" else Fore.RED
            sys.stdout.write(f"\n{icon} {color}{CH[side]}: {Style.RESET_ALL}")
            sys.stdout.flush()
            
            for chunk in response_stream:
                if chunk.choices and hasattr(chunk.choices[0].delta, 'content') and chunk.choices[0].delta.content is not None:
                    content = chunk.choices[0].delta.content
                    full_response += content
                    sys.stdout.write(f"{color}{content}{Style.RESET_ALL}")
                    sys.stdout.flush()
                    time.sleep(0.08)

            # 计算输出token并显示
            output_tokens = ai_model.count_tokens(full_response)
            total_tokens = input_tokens + output_tokens
            sys.stdout.write(f" [{total_tokens}]\n")
            sys.stdout.flush()
            
            return full_response, total_tokens
        except Exception as e:
            print(f"\n{Fore.RED}Error: {str(e)}{Style.RESET_ALL}")
            return None, 0

    def get_judge_analysis(self, topic, debate_history):
        """获取判官的分析和评判"""
        try:
            debate_text = "\n".join(debate_history)
            prompt = f"""作为一位公正的辩论评判，请对以下关于"{topic}"的辩论进行分析和评判。
要求：
1. 分析双方论据的有效性和逻辑性
2. 评估双方的辩论技巧和表现
3. 指出双方的优点和不足
4. 给出最终的胜负判定和理由

辩论内容：
{debate_text}"""

            # 计算输入token
            input_tokens = self.judge_ai.count_tokens(prompt)

            # 获取流式响应
            response_stream = self.judge_ai.get_stream_response(
                messages=[
                    {"role": "system", "content": "你是一位专业、公正的辩论评判，需要对辩论双方的表现进行分析和评判。"},
                    {"role": "user", "content": prompt}
                ],
            )
            
            if not response_stream:
                return None, 0

            # 准备接收完整响应
            full_response = ""
            
            # 流式输出响应
            sys.stdout.write(f"\n{ICONS['judge']} {Fore.MAGENTA}判官评判：{Style.RESET_ALL}")
            sys.stdout.flush()
            
            for chunk in response_stream:
                if chunk.choices and hasattr(chunk.choices[0].delta, 'content') and chunk.choices[0].delta.content is not None:
                    content = chunk.choices[0].delta.content
                    full_response += content
                    sys.stdout.write(f"{Fore.MAGENTA}{content}{Style.RESET_ALL}")
                    sys.stdout.flush()
                    time.sleep(0.02)

            # 计算输出token并显示
            output_tokens = self.judge_ai.count_tokens(full_response)
            total_tokens = input_tokens + output_tokens
            sys.stdout.write(f" [{total_tokens}]\n")
            sys.stdout.flush()
            
            return full_response, total_tokens
        except Exception as e:
            print(f"\n{Fore.RED}Error: {str(e)}{Style.RESET_ALL}")
            return None, 0

    def get_user_choice(self):
        """获取用户选择"""
        while True:
            choice = input(f"\n{Fore.YELLOW}是否继续辩论？(y/n): {Style.RESET_ALL}").lower().strip()
            if choice in ['y', 'n']:
                return choice == 'y'
            print(f"{Fore.RED}请输入 y 或 n{Style.RESET_ALL}")

    def display_debate_history(self, debate_record):
        """显示历史辩论记录"""
        print(f"\n{Fore.CYAN}========= 历史辩论 ========={Style.RESET_ALL}")
        stream_print(f"主题: {debate_record['topic']}", Fore.CYAN)
        stream_print(f"时间: {debate_record['timestamp']}", Fore.CYAN)
        print()

        for entry in debate_record['debate_history']:
            if entry.startswith("正方"):
                stream_print(f"{ICONS['positive']} {entry}", Fore.BLUE)
            elif entry.startswith("反方"):
                stream_print(f"{ICONS['negative']} {entry}", Fore.RED)
            time.sleep(0.5)

        if debate_record['judge_analysis']:
            print(f"\n{Fore.MAGENTA}========= 判官评判 ========={Style.RESET_ALL}")
            stream_print(f"{debate_record['judge_analysis']}", Fore.MAGENTA)
            print(f"{Fore.MAGENTA}========================={Style.RESET_ALL}\n")

    def run_debate(self, topic):
        """运行辩论过程"""
        print(f"\n{ICONS['system']} {Fore.GREEN}开始关于 '{topic}' 的辩论...{Style.RESET_ALL}")
        print(f"{ICONS['system']} {Fore.YELLOW}每轮结束后，你可以选择是否继续辩论{Style.RESET_ALL}\n")
        
        context = f"主题是：{topic}"
        round_num = 1

        try:
            # 正方先发言
            initial_statement, tokens = self.get_ai_response("positive", topic, "请对这个主题发表开场陈述，简短有力。")
            if initial_statement:
                self.debate_history.append(f"正方开场：{initial_statement}")
                context += f"\n正方：{initial_statement}"
                time.sleep(self.calculate_read_time(initial_statement))

            while self.is_running:
                print(f"\n{ICONS['system']} {Fore.CYAN}=== 第 {round_num} 轮辩论 ==={Style.RESET_ALL}")
                
                # 反方回应
                negative_response, neg_tokens = self.get_ai_response("negative", topic, context)
                if not negative_response:
                    break
                self.debate_history.append(f"反方：{negative_response}")
                context += f"\n反方：{negative_response}"
                time.sleep(self.calculate_read_time(negative_response))
                
                # 正方回应
                positive_response, pos_tokens = self.get_ai_response("positive", topic, context)
                if not positive_response:
                    break
                self.debate_history.append(f"正方：{positive_response}")
                context += f"\n正方：{positive_response}"
                time.sleep(self.calculate_read_time(positive_response))
                
                round_num += 1

                # 询问用户是否继续
                if not self.get_user_choice():
                    print(f"\n{ICONS['system']} {Fore.YELLOW}正在请求判官评判...{Style.RESET_ALL}")
                    # 获取判官评判
                    judge_analysis, judge_tokens = self.get_judge_analysis(topic, self.debate_history)
                    if judge_analysis:
                        print(f"\n{ICONS['judge']} {Fore.MAGENTA}========= 判官评判 ========={Style.RESET_ALL}")
                        print(f"{ICONS['judge']} {Fore.MAGENTA}{judge_analysis} ([{judge_tokens}]){Style.RESET_ALL}")
                        print(f"{Fore.MAGENTA}========================={Style.RESET_ALL}\n")
                        
                        # 保存辩论记录
                        filename = DebateRecord.save_debate(topic, self.debate_history, judge_analysis)
                        print(f"{ICONS['system']} {Fore.GREEN}辩论记录已保存至: {filename}{Style.RESET_ALL}")
                    break

        except KeyboardInterrupt:
            print(f"\n\n{ICONS['system']} {Fore.YELLOW}辩论被强制终止{Style.RESET_ALL}")
        except Exception as e:
            print(f"\n{ICONS['system']} {Fore.RED}发生错误: {str(e)}{Style.RESET_ALL}")

def main():
    debate = AIDebate()
    kb_handler = KeyboardHandler()
    print(f"{ICONS['system']} {Fore.CYAN}欢迎使用AI辩论系统！{Style.RESET_ALL}")
    
    while True:
        options = ["开始新的辩论", "查看历史辩论"]
        selected = 0
        num_options = len(options)
        
        # 显示初始菜单
        print(f"\n{ICONS['system']} 请使用↑↓键选择，回车确认：")
        display_menu(options, selected)
        
        kb_handler.init_terminal()
        try:
            while True:
                key = kb_handler.get_key()
                if key == 'up' and selected > 0:
                    selected -= 1
                    clear_lines(num_options)
                    display_menu(options, selected)
                elif key == 'down' and selected < num_options - 1:
                    selected += 1
                    clear_lines(num_options)
                    display_menu(options, selected)
                elif key == 'enter':
                    clear_lines(num_options + 1)  # +1 for the prompt line
                    break
        finally:
            kb_handler.restore_terminal()

        if selected == 0:  # 开始新的辩论
            topic = input(f"\n{Fore.YELLOW}请输入辩论主题: {Style.RESET_ALL}")
            debate.run_debate(topic)
        else:  # 查看历史辩论
            debates = DebateRecord.load_debates()
            if not debates:
                print(f"\n{ICONS['system']} {Fore.YELLOW}暂无历史辩论记录{Style.RESET_ALL}")
                continue
                
            print(f"\n{ICONS['system']} 历史辩论记录：")
            debate_options = [f"{record['timestamp']} - {record['topic']}" for record in debates]
            debate_options.append("返回主菜单")
            selected = 0
            
            while True:
                clear_lines(len(debate_options) if selected != -1 else 0)
                print(f"\n{ICONS['system']} 请使用↑↓键选择，回车确认：")
                display_menu(debate_options, selected)
                
                kb_handler.init_terminal()
                try:
                    while True:
                        key = kb_handler.get_key()
                        if key == 'up' and selected > 0:
                            selected -= 1
                            clear_lines(len(debate_options))
                            display_menu(debate_options, selected)
                        elif key == 'down' and selected < len(debate_options) - 1:
                            selected += 1
                            clear_lines(len(debate_options))
                            display_menu(debate_options, selected)
                        elif key == 'enter':
                            clear_lines(len(debate_options) + 1)
                            break
                finally:
                    kb_handler.restore_terminal()
                
                if selected == len(debate_options) - 1:  # 返回主菜单
                    break
                elif selected >= 0:
                    debate.display_debate_history(debates[selected])
                    input(f"\n{Fore.YELLOW}按回车键返回...{Style.RESET_ALL}")
                    break

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{ICONS['system']} {Fore.CYAN}感谢使用AI辩论系统，再见！{Style.RESET_ALL}")
    except Exception as e:
        print(f"\n{ICONS['system']} {Fore.RED}发生错误: {str(e)}{Style.RESET_ALL}")
    finally:
        # 确保终端设置被恢复
        if os.name != 'nt':
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, termios.tcgetattr(sys.stdin)) 