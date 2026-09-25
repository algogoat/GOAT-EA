"""Shared immutable configuration projection for single and native batch jobs."""

def configuration_members(configuration):
    fields=('tester','export','strategy')
    if not isinstance(configuration,dict) or not all(key in configuration for key in fields):
        raise ValueError('Complete frozen configuration required')
    if 'batch_members' not in configuration:
        return [{key:configuration[key] for key in fields}]
    members=configuration['batch_members']
    if not isinstance(members,list) or not members:
        raise ValueError('Native batch requires nonempty frozen members')
    for member in members:
        if not isinstance(member,dict) or set(member)!=set(fields):
            raise ValueError('Each native batch member requires exactly tester/export/strategy')
        if member['export']!=configuration['export']:
            raise ValueError('Native batch members must share the frozen export policy')
    if members[0]!={key:configuration[key] for key in fields}:
        raise ValueError('First native member differs from initial tester projection')
    return members
