"""
Google Cloud Monitoring integration for FastAPI latency tracking.

Uses OpenTelemetry with Cloud Monitoring exporter for standardized metrics collection.
"""

import os
import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from opentelemetry import metrics
from opentelemetry.exporter.cloud_monitoring import CloudMonitoringMetricsExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from starlette.middleware.base import BaseHTTPMiddleware

# Get project ID from environment or metadata server
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT")

# Global meter provider reference for shutdown
_meter_provider: MeterProvider | None = None

# Global metrics instruments
_request_latency = None
_request_count = None


def init_monitoring(service_name: str = "poly-paper-trading-api") -> None:
    """
    Initialize the OpenTelemetry meter provider and metrics instruments.
    
    Call this during application startup (in lifespan).
    """
    global _meter_provider, _request_latency, _request_count
    
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
    _meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[reader],
    )
    metrics.set_meter_provider(_meter_provider)
    
    # Create a meter for our application
    meter = metrics.get_meter(__name__)
    
    # Create histogram for request latency (in milliseconds)
    _request_latency = meter.create_histogram(
        name="http_request_duration_ms",
        description="HTTP request latency in milliseconds",
        unit="ms",
    )
    
    # Create counter for request count
    _request_count = meter.create_counter(
        name="http_request_count",
        description="Total number of HTTP requests",
        unit="1",
    )


class MonitoringMiddleware(BaseHTTPMiddleware):
    """Middleware to track request latency and count."""
    
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        start_time = time.perf_counter()
        
        # Process the request
        response = await call_next(request)
        
        # Only record metrics if monitoring is initialized
        if _request_latency is not None and _request_count is not None:
            # Calculate latency in milliseconds
            latency_ms = (time.perf_counter() - start_time) * 1000
            
            # Extract endpoint information
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
            
            _request_latency.record(latency_ms, labels)
            _request_count.add(1, labels)
        
        return response


def shutdown_monitoring() -> None:
    """
    Gracefully shutdown monitoring and flush remaining metrics.
    
    Call this during application shutdown.
    """
    global _meter_provider
    if _meter_provider is not None:
        _meter_provider.shutdown()
        _meter_provider = None
