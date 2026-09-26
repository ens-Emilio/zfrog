"""Wget engine: the assets motor of zfrog.

Playwright captures the design; this motor fetches the files behind it so the
reference stays usable offline.
"""

import asyncio
import shutil
from pathlib import Path

from zfrog.engines.base import EngineAdapter, EngineResult
from zfrog.models import JobCreate, ProbeResult
from zfrog.config import settings
from zfrog.utils.rate_limit import retry


class WgetEngine(EngineAdapter):
    """Assets motor: downloads a site's static files (HTML, CSS, images, fonts)
    so a captured reference can be reviewed offline."""
    
    name = "wget"
    
    def __init__(self):
        # Verify wget is installed
        if not shutil.which("wget"):
            raise RuntimeError(
                "wget is not installed. Install it with: "
                "sudo pacman -S wget (Arch) or sudo apt install wget (Debian/Ubuntu)"
            )
    
    @retry(max_retries=3, base_delay=2.0, max_delay=30.0)
    async def execute(
        self,
        job: JobCreate,
        output_dir: Path,
        on_progress=None,
    ) -> EngineResult:
        """Execute wget to mirror a website.
        
        Args:
            job: Job configuration.
            output_dir: Directory to store output.
            on_progress: Optional progress callback.
            
        Returns:
            EngineResult with downloaded files.
            
        Raises:
            Exception: If wget fails after retries.
        """
        from zfrog.utils.cleanup import is_cancelled, CancellationError
        
        # Create mirror subdirectory
        mirror_dir = output_dir / "mirror"
        mirror_dir.mkdir(parents=True, exist_ok=True)
        
        logs = []
        
        # Build wget command
        cmd = [
            "wget",
            "--recursive",
            "--no-parent",
            "--page-requisites",
            "--adjust-extension",
            "--convert-links",
            "--restrict-file-names=windows",
            f"--directory-prefix={mirror_dir}",
            "--no-check-certificate",
            "--timeout=30",
            "--tries=3",
        ]
        
        # Add depth limit
        if job.max_depth and job.max_depth > 0:
            cmd.append(f"--level={job.max_depth}")
        
        # Crawl politeness: delay and jitter between requests
        if job.delay_ms > 0:
            cmd.append(f"--wait={job.delay_ms / 1000:.1f}")
            cmd.append("--random-wait")
        
        # Crawl timeout: the job's budget, capped by the per-URL wget setting
        cmd.append(f"--timeout={min(job.crawl_timeout_s, settings.wget_timeout)}")
        
        # Respect robots.txt
        if not job.respect_robots:
            cmd.append("--execute")
            cmd.append("robots=off")
        
        # Add proxy support
        if settings.proxy_url:
            cmd.extend(["--execute", f"http_proxy={settings.proxy_url}"])
            cmd.extend(["--execute", f"https_proxy={settings.proxy_url}"])
        
        # Add URL
        cmd.append(str(job.url))
        
        logs.append(f"Running wget: {' '.join(cmd)}")
        
        if on_progress:
            on_progress("Starting wget download...")
        
        # Execute wget
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        # Monitor output for progress
        stdout_data = b""
        stderr_data = b""
        
        while True:
            # Check for cancellation
            if await is_cancelled(job.id if hasattr(job, 'id') else ""):
                process.terminate()
                raise CancellationError("Job cancelled during wget execution")
            
            # Read available output
            try:
                stdout_chunk = await asyncio.wait_for(
                    process.stdout.read(1024),
                    timeout=0.1
                )
                stdout_data += stdout_chunk
                
                # Parse progress from wget output
                if on_progress and stdout_chunk:
                    lines = stdout_chunk.decode("utf-8", errors="replace").split("\n")
                    for line in lines:
                        if "Downloading:" in line or "%" in line:
                            on_progress(line.strip()[:100])
            except asyncio.TimeoutError:
                pass
            
            try:
                stderr_chunk = await asyncio.wait_for(
                    process.stderr.read(1024),
                    timeout=0.1
                )
                stderr_data += stderr_chunk
            except asyncio.TimeoutError:
                pass
            
            # Check if process finished
            if process.returncode is not None:
                break
        
        if stdout_data:
            logs.append(stdout_data.decode("utf-8", errors="replace"))
        if stderr_data:
            logs.append(stderr_data.decode("utf-8", errors="replace"))
        
        if process.returncode != 0:
            logs.append(f"wget exited with code {process.returncode}")
        
        # Scan output directory for files
        files = []
        total_bytes = 0
        
        if mirror_dir.exists():
            for file_path in mirror_dir.rglob("*"):
                if file_path.is_file():
                    files.append(file_path)
                    total_bytes += file_path.stat().st_size
        
        if on_progress:
            on_progress(f"Downloaded {len(files)} files ({total_bytes:,} bytes)")
        
        return EngineResult(
            output_dir=mirror_dir,
            files=files,
            total_bytes=total_bytes,
            logs=logs,
        )
    
    def can_handle(self, probe: ProbeResult) -> bool:
        """Check if wget should handle this job."""
        return probe.suggested_engine == "wget"
