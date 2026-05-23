"""
Sistema de notificações em tempo real via Server-Sent Events (SSE).

Usa filas em memória por paciente. Funciona corretamente com
gunicorn em modo single-worker + threads (--workers=1 --threads=N).
"""
import queue
import threading
import json
import time

# Dicionário: patient_id -> queue.Queue
_queues: dict[int, queue.Queue] = {}
_lock = threading.Lock()


def _get_queue(patient_id: int) -> queue.Queue:
    with _lock:
        if patient_id not in _queues:
            _queues[patient_id] = queue.Queue(maxsize=50)
        return _queues[patient_id]


def _remove_queue(patient_id: int):
    with _lock:
        _queues.pop(patient_id, None)


def push_notification(patient_id: int, event_type: str, data: dict):
    """
    Empurra uma notificação para o paciente.
    Chamado quando um profissional faz uma solicitação de acesso.
    """
    q = _get_queue(patient_id)
    payload = json.dumps({'type': event_type, **data})
    try:
        q.put_nowait(payload)
    except queue.Full:
        pass  # descarta se fila cheia (não bloqueia)


def sse_stream(patient_id: int):
    """
    Gerador SSE para o endpoint /notificacoes/stream.
    Mantém a conexão aberta e entrega mensagens assim que chegam.
    """
    q = _get_queue(patient_id)

    # Heartbeat a cada 20 s para manter conexão viva (nginx / proxies)
    heartbeat_interval = 20
    last_heartbeat = time.time()

    try:
        while True:
            try:
                msg = q.get(timeout=1.0)
                yield f'data: {msg}\n\n'
                last_heartbeat = time.time()
            except queue.Empty:
                now = time.time()
                if now - last_heartbeat >= heartbeat_interval:
                    yield ': heartbeat\n\n'
                    last_heartbeat = now
    finally:
        # Se o cliente desconectar, mantemos a fila (pode reconectar)
        pass
