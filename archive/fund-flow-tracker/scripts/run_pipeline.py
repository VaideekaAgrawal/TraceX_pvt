"""
TraceX — Standalone Training & Pipeline Test Runner.
Run this to see FULL training progress with GPU utilization.

Usage:
    python scripts/run_pipeline.py                   # 50k rows (quick test)
    python scripts/run_pipeline.py --max-rows 200000 # 200k rows (medium)
    python scripts/run_pipeline.py --max-rows 0      # FULL dataset (5M rows)
"""
import argparse
import logging
import os
import sys
import time

# Project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configure verbose logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)
logger = logging.getLogger("tracex.runner")


def main():
    parser = argparse.ArgumentParser(description="TraceX Pipeline Runner")
    parser.add_argument("--max-rows", type=int, default=50000,
                        help="Max rows to load (0 = all, default 50000)")
    parser.add_argument("--source", type=str, default="ibm_aml",
                        choices=["ibm_aml", "paysim", "csv"])
    parser.add_argument("--filepath", type=str, default="data/HI-Small_Trans.csv")
    args = parser.parse_args()

    max_rows = args.max_rows if args.max_rows > 0 else None

    logger.info("=" * 70)
    logger.info("🚀 TRACEX PIPELINE RUNNER")
    logger.info("=" * 70)
    logger.info("  Source: %s", args.source)
    logger.info("  File: %s", args.filepath)
    logger.info("  Max Rows: %s", max_rows or "ALL")
    logger.info("=" * 70)

    from services.ingestion import IngestionService
    from services.graph import GraphService
    from services.detection import DetectionService
    from services.investigation import InvestigationService
    from services.detection.ensemble import _GPU_AVAILABLE

    logger.info("  GPU Available: %s", "✅ CUDA (RTX 3060)" if _GPU_AVAILABLE else "❌ CPU only")
    logger.info("=" * 70)

    # ── Step 1: Ingestion ──
    t0 = time.time()
    logger.info("\n📥 INGESTION")
    ingestion = IngestionService()
    accounts_df, txns_df = ingestion.ingest(
        source=args.source, filepath=args.filepath, max_rows=max_rows,
    )
    logger.info("   ✅ Loaded %d accounts, %d transactions (%.1fs)",
                len(accounts_df), len(txns_df), time.time() - t0)

    # ── Step 2: Graph ──
    t0 = time.time()
    logger.info("\n🔗 GRAPH CONSTRUCTION")
    graph_svc = GraphService()
    graph_svc.build(accounts_df, txns_df)
    stats = graph_svc.get_stats()
    logger.info("   ✅ Graph: %d nodes, %d edges, %d components (%.1fs)",
                stats["num_nodes"], stats["num_edges"], stats["num_components"],
                time.time() - t0)

    # ── Step 3: Detection (includes ML training) ──
    t0 = time.time()
    logger.info("\n🔍 DETECTION PIPELINE (GPU training starts here)")
    detection = DetectionService()
    summary = detection.run_full_pipeline(graph_svc, accounts_df, txns_df)
    logger.info("   Total detection pipeline: %.1fs", time.time() - t0)

    # ── Step 4: Investigation ──
    t0 = time.time()
    logger.info("\n📋 INVESTIGATION")
    investigation = InvestigationService()
    investigation.create_alerts_from_detections(detection.detection_results)
    case_stats = investigation.get_case_stats()
    logger.info("   ✅ Alerts: %d, Cases: %d (%.1fs)",
                case_stats.get("total_alerts", 0), case_stats.get("total_cases", 0),
                time.time() - t0)

    # ── Summary ──
    logger.info("\n" + "=" * 70)
    logger.info("🏁 PIPELINE COMPLETE")
    logger.info("=" * 70)
    logger.info("  Accounts analysed: %d", summary.get("accounts_analysed", 0))
    logger.info("  Features extracted: %d per account", summary.get("features_extracted", 0))
    logger.info("  Anomalies (IF): %d", summary.get("anomalies_flagged", 0))
    logger.info("  Detections:")
    for det_type, count in summary.get("detection_counts", {}).items():
        logger.info("    • %s: %d", det_type, count)
    logger.info("  Risk distribution: %s", summary.get("risk_distribution", {}))
    logger.info("  Pipeline time: %s", summary.get("total_pipeline_time_sec", "?"))
    logger.info("  Device: %s", summary.get("device", "?"))

    if summary.get("fraud_metrics"):
        fm = summary["fraud_metrics"]
        logger.info("\n  📊 ML METRICS:")
        logger.info("    Precision: %.4f", fm.get("precision", 0))
        logger.info("    Recall:    %.4f", fm.get("recall", 0))
        logger.info("    F1 Score:  %.4f", fm.get("f1", 0))
        logger.info("    AUC-ROC:   %.4f", fm.get("auc_roc", 0))
        logger.info("    Training Time: %.1fs", fm.get("training_time_sec", 0))
        logger.info("    Device Used: %s", fm.get("device", "?"))
        logger.info("    Train Size: %d", fm.get("train_size", 0))
        logger.info("    Test Size: %d", fm.get("test_size", 0))
        logger.info("    Positive Rate: %.4f", fm.get("positive_rate", 0))
    else:
        logger.warning("\n  ⚠️ No ML metrics — dataset may lack `is_laundering` labels")

    logger.info("\n" + "=" * 70)
    logger.info("Done. Start the API with:")
    logger.info("  python -m uvicorn api.server:app --port 8050")
    logger.info("Or Streamlit:")
    logger.info("  streamlit run app_v3.py")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
