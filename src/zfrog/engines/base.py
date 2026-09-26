"""Abstract base class for engine adapters."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from zfrog.models import JobCreate, ProbeResult


@dataclass
class EngineResult:
    """Result from an engine execution."""
    
    output_dir: Path
    files: list[Path] = field(default_factory=list)
    total_bytes: int = 0
    logs: list[str] = field(default_factory=list)


class EngineAdapter(ABC):
    """Base interface for all extraction engines.
    
    Each engine wraps a specific tool (wget, playwright, etc.) and provides
    a unified interface for the orchestrator.
    """
    
    name: str  # "wget", "playwright", "static_file"
    
    @abstractmethod
    async def execute(
        self,
        job: JobCreate,
        output_dir: Path,
        on_progress: Callable[[str], Any] | None = None,
    ) -> EngineResult:
        """Execute the engine for a given job.
        
        Args:
            job: The job configuration.
            output_dir: Where to write output files. Must be created by engine.
            on_progress: Optional callback for progress updates.
            
        Returns:
            EngineResult with output files and metadata.
        """
        ...
    
    @abstractmethod
    def can_handle(self, probe: ProbeResult) -> bool:
        """Check if this engine can handle the given probe result.
        
        Args:
            probe: Result from URL probing.
            
        Returns:
            True if this engine should handle the job.
        """
        ...
