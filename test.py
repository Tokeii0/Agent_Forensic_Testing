from agents import Agent, Runner, AsyncOpenAI,OpenAIChatCompletionsModel,function_tool
from openai import Stream
from pydantic import BaseModel, ValidationError

from agents.extensions.handoff_prompt import prompt_with_handoff_instructions
from openai.types.responses import ResponseTextDeltaEvent
from dotenv import load_dotenv

import asyncio


load_dotenv()

# 配置自定义客户端
ark_client = AsyncOpenAI(
    base_url="xxxxx",
    api_key="xxxxx"
)


# 定义工具函数
@function_tool
def get_profile(memory_dump_path: str):
    import subprocess
    vol2_path = 'vol2.exe'
    command = [vol2_path, '-f', memory_dump_path, 'imageinfo']
    result = subprocess.run(command, capture_output=True, text=True)
    return result.stdout

@function_tool
def get_process(memory_dump_path: str, profile: str):
    import subprocess
    vol2_path = 'vol2.exe'
    command = [vol2_path, '-f', memory_dump_path, 'pslist', f'--profile={profile}']
    result = subprocess.run(command, capture_output=True, text=True)
    return result.stdout

@function_tool
def use_filescan(memory_dump_path: str, profile: str, Keywords: str):
    import subprocess
    vol2_path = 'vol2.exe'
    # 使用 shell=True 让管道符能正常工作
    command = f'{vol2_path} -f {memory_dump_path} --profile={profile} filescan | findstr {Keywords}'
    result = subprocess.run(command, capture_output=True, text=False, shell=True)
    try:
        # 尝试用 utf-8 解码
        return result.stdout.decode('utf-8')
    except UnicodeDecodeError:
        # 如果 utf-8 解码失败，尝试用 latin-1 编码（可以处理任何字节序列）
        return result.stdout.decode('latin-1')

@function_tool
def use_dumpfiles(memory_dump_path: str, profile: str, offset: str):
    import subprocess
    vol2_path = 'vol2.exe'
    # 使用 shell=True 让管道符能正常工作
    command = f'{vol2_path} -f {memory_dump_path} --profile={profile} dumpfiles -Q {offset} --dump-dir=output'
    result = subprocess.run(command, capture_output=True, text=True, shell=True)
    return result.stdout

@function_tool
def use_command(memory_dump_path: str, profile: str, command: str):
    import subprocess
    vol2_path = 'vol2.exe'
    # 使用 shell=True 让管道符能正常工作
    command = f'{vol2_path} -f {memory_dump_path} --profile={profile} {command}'
    result = subprocess.run(command, capture_output=True, text=True, shell=True)
    return result.stdout

@function_tool
def read_file(file_path: str):
    # 读取output目录下的文件
    import os
    for root, dirs, files in os.walk('output'):
        for file in files:
            if file == file_path:
                with open(os.path.join(root, file), 'r', encoding='utf-8') as f:
                    return f.read()

# vol2获取内存镜像profile的智能体
vol2_getprofile_agent = Agent(
    name="Profile获取大师",
    handoff_description = "获取内存镜像的profile信息",
    instructions='你是一名专业的内存取证专家，擅长从内存镜像中提取profile信息,当你不知道profile时，你只需要返回最佳的profile选项即可',
    model=OpenAIChatCompletionsModel(
        model="ep-20250205093312-7ppjn", 
        openai_client=ark_client
    ),
    tools=[get_profile]
)

# vol2 查看进程的智能体
vol2_getprocess_agent = Agent(
    name="进程查看大师",
    handoff_description = "查看内存镜像的进程信息",
    instructions='你是一名专业的内存取证专家，你将分析内存镜像中的进程信息，根据用户的问题提供分析结果',
    model=OpenAIChatCompletionsModel(
        model="ep-20250205093312-7ppjn", 
        openai_client=ark_client
    ),
    tools=[get_process]
)

vol2_command_agent = Agent(
    name="vol2命令执行大师",
    handoff_description = "执行vol2命令",
    instructions='''
    你是一名专业的内存取证专家,擅长各种vol2命令
    例如:
    进程列表(pslist),网络扫描(netscan),命令行(cmdline),剪贴板(clipboard),编辑框(editbox),命令扫描(cmdscan),控制台(consoles),
    带参数执行，一般是--PID=XXXX,一般需要先看进程列表来确定PID
    你还会带参数执行环境变量(envars),服务扫描(svcscan)，DLL列表(dlllist)
    ''',
    model=OpenAIChatCompletionsModel(
        model="ep-20250205093312-7ppjn", 
        openai_client=ark_client
    ),
    tools=[use_command]
)

# vol2 查看指定位置的文件的智能体
vol2_getfile_agent = Agent(
    name="文件分析大师",
    handoff_description = "分析查看内存镜像中的文件",
    instructions='''
        你是一名专业的内存取证专家，擅长从内存镜像中提取文件信息
        例如:用户需要查看桌面上的文件
        1. 你会提取关键词desktop,然后使用工具use_filescan来搜索文件
        2. 然后调用use_dumpfiles工具来导出用户需求的相关可疑文件，例如导出pass.txt，实际上生成的文件名为"file.None.0xfffffa801a9c1660.dat"
        3. 你需要告诉 实际输出的文件路径 例如 "output/file.None.0xfffffa801a9c1660.dat"
        4. 最后使用read_file工具来读取文件内容'
        <需要注意的是>：
        read_file
        一般读取的文件在output目录下
        你需要通过构造文件名来读取文件内容,例如dumpfiles提取出来的文件一般为"file.None.0xfffffa801a9c1660.dat"这种格式,一半
        file_path 为 "output/file.None.0xfffffa801a9c1660.dat"
        ''',
        
    model=OpenAIChatCompletionsModel(
        model="ep-20250205093312-7ppjn", 
        openai_client=ark_client
    ),
    tools=[use_filescan,use_dumpfiles,read_file]
    
)


triage_agent = Agent(
    name="triage_agent",
    instructions=prompt_with_handoff_instructions('你将会根据用户需求，选择合适的智能体来处理问题'),
    model=OpenAIChatCompletionsModel(
        model="ep-20250205093312-7ppjn", 
        openai_client=ark_client
    ),
    handoffs=[vol2_getprocess_agent,vol2_command_agent],
    tools=[get_process,use_command]
)


# 程序入口
async def main(user_prompt: str):
    result = Runner.run_streamed(triage_agent, user_prompt)
    async for event in result.stream_events():
        if event.type == "raw_response_event" and isinstance(event.data, ResponseTextDeltaEvent):
            print(event.data.delta, end="", flush=True)
        
if __name__ == '__main__':
    asyncio.run(main('看看这个内存镜像进程中有没有可疑的地方,内存镜像是:test.raw，已知这个镜像profile为Win7SP1x64'))
