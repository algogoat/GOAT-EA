"""Read-only host resource observations; specifications are not a speed model."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess


def windows_resources():
    # Fixed query: no caller strings, host names, serial numbers or process data.
    script = ('[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); '
        '$taskCpu=@(Get-CimInstance Win32_Processor -ErrorAction Stop | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors); '
        '$taskOs=Get-CimInstance Win32_OperatingSystem -ErrorAction Stop; '
        '@{processors=$taskCpu;os=$taskOs.Caption;architecture=$taskOs.OSArchitecture;'
        'total_memory_kib=$taskOs.TotalVisibleMemorySize;free_memory_kib=$taskOs.FreePhysicalMemory} | ConvertTo-Json -Depth 4 -Compress')
    shell=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    if not shell.is_file():raise OSError('Windows PowerShell unavailable at system path')
    raw = subprocess.check_output([str(shell),'-NoProfile','-NonInteractive','-Command',script],
                                  text=True,encoding='utf-8-sig',timeout=20,stderr=subprocess.DEVNULL,
                                  creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return json.loads(raw)


def resource_profile(installation):
    observed = datetime.now(timezone.utc).isoformat()
    result = dict(schema_version=1,observed_at=observed,scope='current_host_snapshot',
        platform=platform.system(),architecture=platform.machine(),cpu_models=[],physical_cores=None,
        logical_processors=os.cpu_count(),memory_total_bytes=None,memory_available_bytes=None,
        enabled_mt5_workers=None,mt5_worker_availability='unknown',disks=[],unavailable=[],
        execution_ready=False,launch_permitted=False,
        limitations=['CPU/RAM figures do not predict optimization speed or enabled MT5 workers',
            'Available RAM and disk space are point-in-time observations',
            'This snapshot does not establish the hardware, load, workers or cache conditions of historical runs'])
    if os.name == 'nt':
        try:
            native=windows_resources();processors=native['processors']
            def positive(value):
                if isinstance(value,bool):raise ValueError('Invalid resource number')
                number=int(value)
                if number<=0 or str(number)!=str(value):raise ValueError('Invalid resource number')
                return number
            if not isinstance(processors,list) or not processors or len(processors)>256:
                raise ValueError('Invalid processor inventory')
            models=[row['Name'].strip() for row in processors]
            cores=sum(positive(row['NumberOfCores']) for row in processors)
            logical=sum(positive(row['NumberOfLogicalProcessors']) for row in processors)
            total=positive(native['total_memory_kib'])*1024
            free=native['free_memory_kib']
            if isinstance(free,bool) or str(int(free))!=str(free):raise ValueError('Invalid available memory')
            available=int(free)*1024
            if any(not model or len(model)>256 for model in models) or logical<cores or not 0<=available<=total:
                raise ValueError('Invalid resource snapshot')
            result.update(cpu_models=models,physical_cores=cores,logical_processors=logical,
                memory_total_bytes=total,memory_available_bytes=available,
                platform=str(native['os']),architecture=str(native['architecture']),resource_source='Windows CIM')
        except (OSError,ValueError,KeyError,TypeError,AttributeError,subprocess.SubprocessError):
            result['unavailable'].append('Windows CPU/RAM inventory unavailable; no performance estimate substituted')
    else:
        result['unavailable'].append('Detailed CPU/RAM inventory requires Windows; portable disk/logical-CPU observations only')
    for role,key in [('terminal_data','terminal_data_root'),('common_files','common_files_root'),('controller_state','controller_state_root')]:
        root=Path(installation[key]).resolve()
        probe=root
        while not probe.exists() and probe.parent!=probe:probe=probe.parent
        item=dict(role=role,path=str(root),observed_at=datetime.now(timezone.utc).isoformat(),total_bytes=None,free_bytes=None,used_bytes=None)
        try:
            usage=shutil.disk_usage(probe)
            item.update(total_bytes=usage.total,free_bytes=usage.free,used_bytes=usage.used,
                measured_existing_path=str(probe),scope='containing_filesystem_not_directory_size')
        except OSError:item['unavailable']='Filesystem capacity unavailable'
        result['disks'].append(item)
    return result
