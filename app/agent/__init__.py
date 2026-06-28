"""The conversational agent surface — Apex's capstone ``assist`` loop.

A TOP-LEVEL consumer package: ``app.agent.assist`` imports the comprehension
layer and the shipped engine organs ONE-DIRECTIONALLY (nothing in the engine or
intent layers imports back into ``app.agent``), so wiring the conversational
loop can never reintroduce an import cycle.
"""
