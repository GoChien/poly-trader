"""
Google Cloud Monitoring integration for FastAPI latency tracking.

Uses OpenTelemetry with Cloud Monitoring exporter for standardized metrics collection.
"""

import os
import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from opentelemetry import metrics
from opentelemetry.exporter.cloud_monitoring import CloudMonitoringMetricsExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

# Get project ID from environment or metadata server
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT")


def setup_monitoring(app: FastAPI, service_name: str = "poly-paper-trading-api") -> None:
    """
    Set up Cloud Monitoring with OpenTelemetry for the FastAPI application.
    
    Args:
        app: The FastAPI application instance
        service_name: Name of the service for metric labels
    """
    # Create resource with service information
    resource = Resource.create({
        "service.name": service_name,
        "service.namespace": "poly-trader",
    })
    
    # Set up the Cloud Monitoring exporter
    exporter = CloudMonitoringMetricsExporter(project_id=PROJECT_ID)
    
    # Create a metric reader that exports every 60 seconds
    reader = PeriodicExportingMetricReader(
        exporter,
        export_interval_millis=60000,  # Export every 60 seconds
    )
    
    # Create and set the meter provider
    provider = MeterProvider(
        resource=resource,
        metric_readers=[reader],
    )
    metrics.set_meter_provider(provider)
    
    # Create a meter for our application
    meter = metrics.get_meter(__name__)
    
    # Create histogram for request latency (in milliseconds)
    request_latency = meter.create_histogram(
        name="http_request_duration_ms",
        description="HTTP request latency in milliseconds",
        unit="ms",
    )
    
    # Create counter for request count
    request_count = meter.create_counter(
        name="http_request_count",
        description="Total number of HTTP requests",
        unit="1",
    )
    
    @app.middleware("http")
    async def monitoring_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Middleware to track request latency and count."""
        start_time = time.perf_counter()
        
        # Process the request
        response = await call_next(request)
        
        # Calculate latency in milliseconds
        latency_ms = (time.perf_counter() - start_time) * 1000
        
        # Extract endpoint information
        # Use route path if available, otherwise use the raw path
        route = request.scope.get("route")
        endpoint = route.path if route else request.url.path
        method = request.method
        status_code = str(response.status_code)
        
        # Record metrics with labels
        labels = {
            "endpoint": endpoint,
            "method": method,
            "status_code": status_code,
        }
        
        request_latency.record(latency_ms, labels)
        request_count.add(1, labels)
        
        return response
    
    # Store meter provider on app state for cleanup
    app.state.meter_provider = provider


async def shutdown_monitoring(app: FastAPI) -> None:
    """
    Gracefully shutdown monitoring and flush remaining metrics.
    
    Call this during application shutdown.
    """
    if hasattr(app.state, "meter_provider"):
        app.state.meter_provider.shutdown()

