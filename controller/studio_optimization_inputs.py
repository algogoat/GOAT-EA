"""Render native optimization flags explicitly; frozen SET bytes stay untouched."""
def explicit_optimization_inputs(text, schema):
    lines=[]
    for line in text.splitlines(keepends=True):
        body=line.rstrip('\r\n'); ending=line[len(body):]
        if '=' in body and not body.lstrip().startswith(';'):
            key,value=body.split('=',1)
            definition=schema['inputs'].get(key)
            if definition and definition['optimizable'] and definition['type']!='string' and '||' not in value:
                body=key+'='+value+'||'+value+'||0||'+value+'||N'
        lines.append(body+ending)
    return ''.join(lines)
