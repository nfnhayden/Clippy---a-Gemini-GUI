import json
import os

def load_animations(agent_path=None):
    """
    Parses the agent.js file (which is a JSON-like structure wrapped in a function call).
    Returns a dictionary of animations.
    """
    if agent_path is None:
        agent_path = os.path.join(os.path.dirname(__file__), "agent.js")
    
    if not os.path.exists(agent_path):
        raise FileNotFoundError(f"Agent file not found: {agent_path}")

    with open(agent_path, "r", encoding="utf-8") as f:
        content = f.read().strip()

    # The file is expected to be: clippy.ready('Clippy', {JSON_OBJECT})
    # We need to extract the JSON object.
    
    # Use regex to find the JSON object
    import re
    match = re.search(r"clippy\.ready\('Clippy', \s*({.*})", content, re.DOTALL)
    if match:
        content = match.group(1)
        # Remove trailing ); if caught (though greedy match might need care, usually last char is })
        # Actually json.loads stops at valid json usually? No.
        # Let's clean up the end if needed.
        if content.strip().endswith(");"):
             content = content.strip()[:-2]
        elif content.strip().endswith(")"):
             content = content.strip()[:-1]
    else:
        # Fallback to simple slicing if regex fails
        start_marker = "clippy.ready('Clippy', "
        if start_marker in content:
             content = content.split(start_marker)[1]
             if content.strip().endswith(");"):
                content = content.strip()[:-2]
             elif content.strip().endswith(")"):
                content = content.strip()[:-1]
    
    try:
        data = json.loads(content)
        return data
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}")
        return {}

if __name__ == "__main__":
    data = load_animations()
    print(f"Loaded {len(data.get('animations', {}))} animations.")
    print("Keys:", list(data.get('animations', {}).keys()))

