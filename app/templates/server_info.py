import os
import psutil


def _server_stats():
    # Intenta amb psutil (recomanat)
    try:
        cpu_count = psutil.cpu_count(logical=True) or (os.cpu_count() or 0)
        cpu_percent = float(psutil.cpu_percent(interval=0.2))  # petita mostra
        vm = psutil.virtual_memory()
        # "en ús" més realista: total - available
        mem_used = vm.total - vm.available
        mem_total_gb = round(vm.total / (1024 ** 3), 2)
        mem_used_gb  = round(mem_used / (1024 ** 3), 2)
        mem_used_pct = round(100.0 * mem_used / vm.total, 1) if vm.total else 0.0
        return dict(
            cpu_count=cpu_count,
            cpu_percent=cpu_percent,
            mem_total_gb=mem_total_gb,
            mem_used_gb=mem_used_gb,
            mem_used_pct=mem_used_pct,
        )
    except Exception:
        # Fallback lleuger: potser en contenedor sense psutil
        cpu_count = os.cpu_count() or 0
        mem_total_gb = mem_used_gb = mem_used_pct = 0.0
        try:
            # Només Linux: /proc/meminfo (kB)
            with open("/proc/meminfo") as f:
                info = dict(line.split(":")[0].strip(), *line.split(":")[1:])  # not used, do simple parse below
        except Exception:
            pass
        try:
            meminfo = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    k, v = line.split(":")
                    meminfo[k.strip()] = int(v.strip().split()[0])  # kB
            total_kb = meminfo.get("MemTotal", 0)
            avail_kb = meminfo.get("MemAvailable", 0)
            used_kb = max(total_kb - avail_kb, 0)
            mem_total_gb = round(total_kb / (1024 ** 2), 2)
            mem_used_gb  = round(used_kb  / (1024 ** 2), 2)
            mem_used_pct = round(100.0 * used_kb / total_kb, 1) if total_kb else 0.0
        except Exception:
            pass
        return dict(
            cpu_count=cpu_count,
            cpu_percent=0.0,
            mem_total_gb=mem_total_gb,
            mem_used_gb=mem_used_gb,
            mem_used_pct=mem_used_pct,
        )