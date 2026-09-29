"""Classical mechanics helpers with fictional parameters kept explicit.

These functions cover non-relativistic, deliberately simplified estimates.
They do not model biological limits, object failure, momentum reaction paths,
or fictional force fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


class PhysicsInputError(ValueError):
    pass


def _nonnegative(**values: float) -> None:
    if any(not isfinite(value) or value < 0 for value in values.values()):
        raise PhysicsInputError("inputs must be finite and non-negative")


@dataclass(frozen=True)
class EnergyState:
    available_j: float
    capacity_j: float

    def __post_init__(self) -> None:
        _nonnegative(available_j=self.available_j, capacity_j=self.capacity_j)
        if self.available_j > self.capacity_j:
            raise PhysicsInputError("available reserve cannot exceed capacity")


@dataclass(frozen=True)
class EnergyStep:
    state: EnergyState
    harvested_j: float
    expended_j: float


def advance_energy(
    state: EnergyState, *, duration_s: float, irradiance_w_m2: float,
    collection_area_m2: float, absorption_efficiency: float,
    abilities_w: float, baseline_w: float,
) -> EnergyStep:
    """Apply clipped reserve balance: E' = clip(E + (ηAI-Pa-Pb)Δt, 0, Emax)."""
    _nonnegative(duration_s=duration_s, irradiance_w_m2=irradiance_w_m2,
                 collection_area_m2=collection_area_m2,
                 abilities_w=abilities_w, baseline_w=baseline_w)
    if not isfinite(absorption_efficiency) or not 0 <= absorption_efficiency <= 1:
        raise PhysicsInputError("absorption efficiency must be within [0, 1]")
    harvested = absorption_efficiency * collection_area_m2 * irradiance_w_m2 * duration_s
    expended = (abilities_w + baseline_w) * duration_s
    remaining = min(state.capacity_j, max(0.0, state.available_j + harvested - expended))
    return EnergyStep(EnergyState(remaining, state.capacity_j), harvested, expended)


@dataclass(frozen=True)
class LiftResult:
    support_force_n: float
    useful_work_j: float
    required_reserve_j: float
    remaining_reserve_j: float
    feasible: bool


def resolve_lift(
    *, mass_kg: float, height_m: float, available_energy_j: float,
    max_force_n: float, efficiency: float, gravity_m_s2: float = 9.81,
) -> LiftResult:
    """Constant-speed lift; excludes object failure and support-field mechanics."""
    _nonnegative(mass_kg=mass_kg, height_m=height_m,
                 available_energy_j=available_energy_j,
                 max_force_n=max_force_n, gravity_m_s2=gravity_m_s2)
    if not isfinite(efficiency) or not 0 < efficiency <= 1:
        raise PhysicsInputError("efficiency must be greater than 0 and at most 1")
    force = mass_kg * gravity_m_s2
    work = force * height_m
    required = work / efficiency
    return LiftResult(force, work, required, max(0.0, available_energy_j - required),
                      force <= max_force_n and required <= available_energy_j)


@dataclass(frozen=True)
class FlightEstimate:
    drag_force_n: float
    acceleration_m_s2: float


def estimate_flight(
    *, mass_kg: float, thrust_n: float, gravity_m_s2: float,
    air_density_kg_m3: float, drag_coefficient: float,
    frontal_area_m2: float, speed_m_s: float,
) -> FlightEstimate:
    """Upward thrust against gravity and opposing quadratic atmospheric drag."""
    _nonnegative(mass_kg=mass_kg, thrust_n=thrust_n, gravity_m_s2=gravity_m_s2,
                 air_density_kg_m3=air_density_kg_m3,
                 drag_coefficient=drag_coefficient, frontal_area_m2=frontal_area_m2,
                 speed_m_s=speed_m_s)
    if mass_kg == 0:
        raise PhysicsInputError("mass must be positive")
    drag = 0.5 * air_density_kg_m3 * drag_coefficient * frontal_area_m2 * speed_m_s**2
    acceleration = (thrust_n - mass_kg * gravity_m_s2 - drag) / mass_kg
    return FlightEstimate(drag, acceleration)


@dataclass(frozen=True)
class ImpactEstimate:
    kinetic_energy_j: float
    transferred_energy_j: float
    average_force_n: float


def estimate_impact(
    *, effective_mass_kg: float, speed_m_s: float,
    stopping_distance_m: float, transfer_fraction: float = 1.0,
) -> ImpactEstimate:
    """Non-relativistic kinetic energy and mean force over stopping distance."""
    _nonnegative(effective_mass_kg=effective_mass_kg, speed_m_s=speed_m_s)
    if not isfinite(stopping_distance_m) or stopping_distance_m <= 0:
        raise PhysicsInputError("stopping distance must be positive and finite")
    if not isfinite(transfer_fraction) or not 0 <= transfer_fraction <= 1:
        raise PhysicsInputError("transfer fraction must be within [0, 1]")
    kinetic = 0.5 * effective_mass_kg * speed_m_s**2
    transferred = kinetic * transfer_fraction
    return ImpactEstimate(kinetic, transferred, transferred / stopping_distance_m)
