"""Hidden, loopback-only controls for local reservation fault injection."""

from ipaddress import ip_address

from fastapi import APIRouter, Depends, HTTPException, Request, status

from inventory_service.faults import ReservationFault, ReservationFaultController


def require_loopback(request: Request) -> None:
    """Reject control requests that did not originate on loopback."""
    host = request.client.host if request.client is not None else ""
    if host.lower() == "localhost":
        return
    try:
        is_loopback = ip_address(host).is_loopback
    except ValueError:
        is_loopback = False
    if not is_loopback:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Fault controls are available only from loopback.",
        )


router = APIRouter(
    prefix="/internal/faults",
    include_in_schema=False,
    dependencies=[Depends(require_loopback)],
)


def get_fault_controller(request: Request) -> ReservationFaultController:
    """Return the replaceable controller owned by this application."""
    return request.app.state.fault_controller


@router.get("/reservation", response_model=ReservationFault)
async def read_reservation_fault(
    controller: ReservationFaultController = Depends(get_fault_controller),
) -> ReservationFault:
    """Read the active development reservation fault."""
    return await controller.read()


@router.put("/reservation", response_model=ReservationFault)
async def update_reservation_fault(
    configuration: ReservationFault,
    controller: ReservationFaultController = Depends(get_fault_controller),
) -> ReservationFault:
    """Replace the active development reservation fault."""
    return await controller.update(configuration)


@router.delete("/reservation", response_model=ReservationFault)
async def reset_reservation_fault(
    controller: ReservationFaultController = Depends(get_fault_controller),
) -> ReservationFault:
    """Reset the active development reservation fault."""
    return await controller.reset()
