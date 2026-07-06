"""Orchestration layer — wires ingestion, graph, detection and investigation
into one reusable pipeline so API routes don't each duplicate the sequence."""
from services.pipeline.analysis_pipeline import AnalysisPipeline

__all__ = ["AnalysisPipeline"]
