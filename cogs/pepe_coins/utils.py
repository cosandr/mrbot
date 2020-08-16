from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Tuple, Union

import asyncpg

from .errors import InvalidPepeUnit

q_type_fields: str = r"SELECT attname FROM pg_attribute WHERE attrelid=(SELECT typrelid FROM pg_type WHERE typname=$1) AND attname !~ '^\.'"
q_type_exists: str = "SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname=$1)"

unit_param: Dict[str, Dict[str, Union[str, int, float]]] = {
    'midget': {'name': 'Midgets', 'buy': 100, 'cps': 0.04, 'r': 1.1, 'ucost': 200, 'ucps': 0.03, 'ur': 1.5},
    'worker': {'name': 'Workers', 'buy': 1000.0, 'cps': 8.0, 'r': 1.2, 'ucost': 2000.0, 'ucps': 0.02, 'ur': 1.4},
    'factory': {'name': 'Factories', 'buy': 1000000.0, 'cps': 40.0, 'r': 1.3, 'ucost': 2000000.0, 'ucps': 0.05, 'ur': 1.3}
}


sql_ref: Dict[str, Dict[str, str]] = {
    "player": {"name": "VARCHAR(200)", "id": "BIGINT", "coins": "NUMERIC(50, 0)"},
    "stats": {"claim_time": "TIMESTAMP", "streak": "INTEGER", "last_tick": "TIMESTAMP", "tcoins": "NUMERIC(50, 0)"},
    "base_unit": {"count": "INTEGER", "level": "INTEGER"},
    "units": {unit: "pepe_base_unit" for unit in unit_param.keys()}
}


units_struc: Dict[str, Dict[str, int]] = {unit: dict.fromkeys(sql_ref['base_unit'], 0) for unit in unit_param.keys()}
stats_struc: Dict[str, Union[datetime, int, Decimal, None]] = {}
for k, v in sql_ref['stats'].items():
    if v == "TIMESTAMP":
        stats_struc[k] = None
    else:
        stats_struc[k] = 0


async def _check_types(name: str, ref: Dict[str, str], db: List[str], con: asyncpg.Connection) -> None:
    for k, v in ref.items():
        if k not in db:
            await con.execute(f"ALTER TYPE {name} ADD ATTRIBUTE {k} {v}")
            db.append(k)
            print(f"Add missing attr {k}")
    # Check if we have have to remove old items
    for k in db:
        if k not in ref:
            await con.execute(f"ALTER TYPE {name} DROP ATTRIBUTE {k}")
            print(f"Remove attr {k}")


def _make_generic_type(ref: Dict[str, str], name: str) -> str:
    q = f"CREATE TYPE {name} AS ("
    for k, v in ref.items():
        q += f"{k} {v},"
    q = f"{q[:-1]});"
    return q


async def match_sql(pool: asyncpg.pool.Pool) -> None:
    """Ensure PSQL table matches defined structure"""
    async with pool.acquire() as con:
        for name, ref in sql_ref.items():
            sql_name = f"pepe_{name}"
            fields = await con.fetch(q_type_fields, sql_name)
            db = [el['attname'] for el in fields]
            if len(db) == 0:
                await con.execute(_make_generic_type(ref, sql_name))
                print(f"Created {sql_name} type")
            else:
                await _check_types(sql_name, ref, db, con)


def buy_cost(unit: str, unit_dict: dict, amount: int) -> int:
    if unit not in unit_param:
        raise InvalidPepeUnit
    r = unit_param[unit]['r']
    return int((((r**unit_dict['count'])*((r**amount)-1))/(r-1))*unit_param[unit]['buy'])


def upgrade_cost(unit: str, unit_dict: dict, amount: int) -> int:
    if unit not in unit_param:
        raise InvalidPepeUnit
    ur = unit_param[unit]['ur']
    return int((((ur**unit_dict['level'])*((ur**amount)-1))/(ur-1))*unit_param[unit]['ucost'])


def cps(psql_res: asyncpg.Record) -> float:
    units_dict = {}
    for k, v in dict(psql_res).items():
        units_dict[k] = dict(v)
    cps = 0
    for k, v in unit_param.items():
        unit_cps = v['cps']*units_dict[k]['count']
        upg_cps = v['cps']*v['ucps']*units_dict[k]['count']*units_dict[k]['level']
        cps += unit_cps + upg_cps
    return cps


def tick(psql_res: asyncpg.Record) -> float:
    if psql_res['last_tick']:
        td = datetime.utcnow() - psql_res['last_tick']
        print(td)
        return cps(psql_res['units'])*td.seconds
    else:
        return cps(psql_res['units'])


def prod_calc(psql_res: asyncpg.Record) -> Tuple[Dict, Dict, Dict, float]:
    units_dict = {}
    for k, v in dict(psql_res).items():
        units_dict[k] = dict(v)
    cost_dict = {unit: {"unit": 0, "level": 0} for unit in unit_param.keys()}
    gen_dict = {unit: {"unit": 0, "level": 0} for unit in unit_param.keys()}
    spent_dict = {unit: {"unit": 0, "level": 0} for unit in unit_param.keys()}
    cps = 0
    for k, v in unit_param.items():
        count = units_dict[k]['count']
        cost_dict[k]['unit'] = v['buy']*(v['r']**count)
        cost_dict[k]['level'] = v['ucost']*(v['ur']**units_dict[k]['level'])
        gen_dict[k]['unit'] = v['cps']*count
        gen_dict[k]['level'] = v['cps']*v['ucps']*count*units_dict[k]['level']
        spent_dict[k]['unit'] = (((v['r'] ** units_dict[k]['count']) - 1) / (v['r'] - 1)) * v['buy']
        spent_dict[k]['level'] = (((v['ur'] ** units_dict[k]['level']) - 1) / (v['ur'] - 1)) * v['ucost']
        cps += gen_dict[k]['unit'] + gen_dict[k]['level']
    # Return dictionaries to make expansion easier.
    return cost_dict, gen_dict, spent_dict, cps
