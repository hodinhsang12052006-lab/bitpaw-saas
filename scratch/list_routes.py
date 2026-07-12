import ast
import re

def analyze_app_routes():
    with open("app.py", "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
        
    routes = []
    
    # We will also parse blueprints from other files
    # but let's focus on app.py first
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            # Check for @app.route decorator
            is_route = False
            route_urls = []
            route_methods = ["GET"] # default
            
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr == 'route':
                    is_route = True
                    # Extract URL
                    if dec.args:
                        url_node = dec.args[0]
                        if isinstance(url_node, ast.Constant):
                            route_urls.append(url_node.value)
                        elif isinstance(url_node, ast.Str): # Python < 3.8
                            route_urls.append(url_node.s)
                    
                    # Extract methods
                    for keyword in dec.keywords:
                        if keyword.arg == 'methods':
                            if isinstance(keyword.value, ast.List):
                                route_methods = [elt.value if isinstance(elt, ast.Constant) else elt.s for elt in keyword.value.elts]
            
            if is_route:
                # Find render_template calls inside this function
                templates = []
                for subnode in ast.walk(node):
                    if isinstance(subnode, ast.Call) and isinstance(subnode.func, ast.Name) and subnode.func.id == 'render_template':
                        if subnode.args:
                            temp_node = subnode.args[0]
                            if isinstance(temp_node, ast.Constant):
                                templates.append(temp_node.value)
                            elif isinstance(temp_node, ast.Str):
                                templates.append(temp_node.s)
                
                routes.append({
                    "urls": route_urls,
                    "function_name": node.name,
                    "methods": route_methods,
                    "templates": templates
                })
                
    return routes

routes = analyze_app_routes()
print(f"Total routes found: {len(routes)}")
for r in routes:
    print(f"URL: {', '.join(r['urls'])} | Function: {r['function_name']} | Methods: {r['methods']} | Templates: {r['templates']}")
