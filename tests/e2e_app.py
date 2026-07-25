from app.main import create_app
from tests.model_gateway_stub import StubModelGateway

app = create_app(model_gateway=StubModelGateway())
