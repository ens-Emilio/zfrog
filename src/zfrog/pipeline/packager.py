"""Packager for creating output archives."""

import zipfile
from pathlib import Path


async def package_zip(source_dir: Path, output_path: Path) -> Path:
    """Create a ZIP archive from a directory.
    
    Args:
        source_dir: Directory containing files to archive.
        output_path: Path for the output ZIP file.
        
    Returns:
        Path to created ZIP file.
    """
    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in source_dir.rglob("*"):
            # Skip the ZIP itself and any directories
            if not file_path.is_file() or file_path.resolve() == output_path.resolve():
                continue
            arcname = file_path.relative_to(source_dir)
            zf.write(file_path, arcname)
    
    return output_path
