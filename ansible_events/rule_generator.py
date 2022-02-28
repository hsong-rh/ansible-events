from durable.lang import ruleset, rule, m
import asyncio
import multiprocessing as mp
from ansible_events.condition_types import (
    Identifier,
    String,
    OperatorExpression,
    Integer,
    Condition,
    ConditionTypes,
    ExistsExpression,
)

from ansible_events.rule_types import RuleSetQueuePlan, ActionContext
from ansible_events.rule_types import Condition as RuleCondition
from ansible_events.inventory import matching_hosts


from typing import Dict, List, Callable


def add_to_plan(
    host_ruleset: str,
    action: str,
    action_args: Dict,
    variables: Dict,
    inventory: Dict,
    hosts: List,
    facts: Dict,
    plan: asyncio.Queue,
    c,
) -> None:
    plan.put_nowait(ActionContext(host_ruleset, action, action_args, variables, inventory, hosts, facts, c))


def visit_condition(parsed_condition: ConditionTypes, condition):
    if isinstance(parsed_condition, Condition):
        return visit_condition(parsed_condition.value, condition)
    elif isinstance(parsed_condition, Identifier):
        return condition.__getattr__(parsed_condition.value)
    elif isinstance(parsed_condition, String):
        return parsed_condition.value
    elif isinstance(parsed_condition, Integer):
        return parsed_condition.value
    elif isinstance(parsed_condition, OperatorExpression):
        if parsed_condition.operator == "!=":
            return visit_condition(parsed_condition.left, condition).__ne__(
                visit_condition(parsed_condition.right, condition)
            )
        elif parsed_condition.operator == "==":
            return visit_condition(parsed_condition.left, condition).__eq__(
                visit_condition(parsed_condition.right, condition)
            )
        else:
            raise Exception(f"Unhandled token {parsed_condition}")
    elif isinstance(parsed_condition, ExistsExpression):
        return visit_condition(parsed_condition.value, condition).__pos__()
    else:
        raise Exception(f"Unhandled token {parsed_condition}")


def generate_condition(ansible_condition: RuleCondition):
    return visit_condition(ansible_condition.value, m)


def make_fn(
    host_ruleset, ansible_rule, variables: Dict, inventory: Dict, hosts: List, facts: Dict, plan: asyncio.Queue
) -> Callable:
    def fn(c):
        logger = mp.get_logger()
        logger.info(f"calling {ansible_rule.name}")
        add_to_plan(
            host_ruleset,
            ansible_rule.action.action,
            ansible_rule.action.action_args,
            variables,
            inventory,
            hosts,
            facts,
            plan,
            c,
        )

    return fn


def generate_rulesets(
    ansible_ruleset_queue_plans: List[RuleSetQueuePlan], variables: Dict, inventory: Dict
):

    logger = mp.get_logger()
    rulesets = []

    for ansible_ruleset, queue, plan in ansible_ruleset_queue_plans:
        host_rulesets = []
        for host in matching_hosts(inventory, ansible_ruleset.hosts):
            host_ruleset = ruleset(f'{ansible_ruleset.name}_{host}')
            with host_ruleset:
                for ansible_rule in ansible_ruleset.host_rules:
                    fn = make_fn(host_ruleset.name, ansible_rule, variables, inventory, [host], {}, plan)
                    r = rule("all", True, generate_condition(ansible_rule.condition))(fn)
                    logger.info(r.define())
            host_rulesets.append(host_ruleset)
        rulesets.append((host_rulesets, queue, plan))

    return rulesets
