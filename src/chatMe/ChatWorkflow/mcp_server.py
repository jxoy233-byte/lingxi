from typing import Any


from fastmcp import FastMCP
import subprocess
import tempfile
import os
import json

server = FastMCP(name="ChatMe Agent Skills", )

@server.tool
def execute_code(code: str, language: str = "python") -> str:
    """在沙盒中执行代码"""
    try:
        if language == "python":
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code)
                temp_file = f.name
            
            result = subprocess.run(
                ["python", temp_file],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            os.unlink(temp_file)
            
            return f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n\nReturn code: {result.returncode}"
        else:
            return f"Unsupported language: {language}"
    except Exception as e:
        return f"Error: {str(e)}"

@server.tool
def list_skills() -> str:
    """列出所有可用的技能"""
    skills_dir = os.path.join(os.path.dirname(__file__), 'skills')
    skills = []
    
    if os.path.exists(skills_dir):
        for file in os.listdir(skills_dir):
            if file.endswith('.py') and file != '__init__.py':
                skills.append(file[:-3])
    
    return json.dumps({"skills": skills})

@server.tool    
def read_skill_file(skill_name: str) -> str:
    """读取技能文件内容"""
    skills_dir = os.path.join(os.path.dirname(__file__), 'skills')
    skill_file = os.path.join(skills_dir, f"{skill_name}.py")
    
    if os.path.exists(skill_file):
        with open(skill_file, 'r', encoding='utf-8') as f:
            return f.read()
    else:
        return f"Skill file not found: {skill_name}"

@server.tool
def create_skill(skill_name: str, content: str) -> str:
    """创建新的技能文件"""
    skills_dir = os.path.join(os.path.dirname(__file__), 'skills')
    if not os.path.exists(skills_dir):
        os.makedirs(skills_dir)
    
    skill_file = os.path.join(skills_dir, f"{skill_name}.py")
    
    try:
        with open(skill_file, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"Skill created successfully: {skill_name}"
    except Exception as e:
        return f"Error creating skill: {str(e)}"

@server.tool        
def delete_skill(skill_name: str) -> str:
    """删除技能文件"""
    skills_dir = os.path.join(os.path.dirname(__file__), 'skills')
    skill_file = os.path.join(skills_dir, f"{skill_name}.py")
    
    if os.path.exists(skill_file):
        try:
            os.unlink(skill_file)
            return f"Skill deleted successfully: {skill_name}"
        except Exception as e:
            return f"Error deleting skill: {str(e)}"
    else:
        return f"Skill file not found: {skill_name}"

if __name__ == "__main__":
    server.run(host="127.0.0.1", port=18080, transport="streamable-http", path="/streamable")
