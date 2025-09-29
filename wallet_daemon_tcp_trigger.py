#!/usr/bin/env python3
"""
@Cryptis (https://cryptix-network.org/)

Full CPAY / Cryptix Wallet Client
- Implements all cryptixwalletd.proto RPCs
- Waits for commands via TCP trigger
- Sends command results back to the trigger client
- Displays all amounts in CPAY decimal format (8 decimals)
- Processes commands sequentially to avoid collisions
- More threads can be added for parallel processing (But stability comes before speed)

**** Not tested in production - please test first ****
"""

import grpc
import socket
from decimal import Decimal
import cryptixwalletd_pb2
import cryptixwalletd_pb2_grpc
import traceback
import json
import threading
import queue
import time
import re

DEFAULT_WALLET_ADDR = "localhost:8082"  # Address and port of the wallet daemon
DEFAULT_TRIGGER_PORT = 9092 # The triggers are received on this port

TRIGGER_PASSWORD = "trigger_password_123"  # <<< Set your password

last_tx_time = 0
tx_lock = threading.Lock()

# An additional security mechanism for multiple simultaneous transactions that specifies the minimum number of seconds between transactions. This gives the daemon time to work.
MIN_TX_INTERVAL = 10 

# Input Validation
ADDRESS_REGEX = re.compile(r"^[A-Za-z0-9\.:]{10,128}$")
ALLOWED_CHARS_REGEX = re.compile(r"^[A-Za-z0-9\s_\-:\.]+$")

# -------------------------
# Helper function for serial sending
# -------------------------
def process_transaction(func):
    """
    Executes the transaction serially and ensures that
    at least MIN_TX_INTERVAL seconds have passed since the last transaction.
    This can prevent collision.
    """
    global last_tx_time
    with tx_lock:
        now = time.time()
        elapsed = now - last_tx_time
        if elapsed < MIN_TX_INTERVAL:
            time.sleep(MIN_TX_INTERVAL - elapsed)
        result = func()
        last_tx_time = time.time()
        return result

# -------------------------
# Wallet Client
# -------------------------
class CPAYWalletClient:
    def __init__(self, wallet_addr=DEFAULT_WALLET_ADDR, timeout=10):
        self.channel = grpc.insecure_channel(wallet_addr)
        self.stub = cryptixwalletd_pb2_grpc.cryptixwalletdStub(self.channel)
        self.timeout = timeout

    def _safe_rpc(self, rpc_func, *args, **kwargs):
        try:
            return rpc_func(*args, **kwargs)
        except grpc.RpcError as e:
            return f"[ERROR] gRPC error: {e.code()} - {e.details()}"
        except Exception as e:
            return f"[ERROR] Unexpected error: {e}\n{traceback.format_exc()}"

    def get_balance(self):
        return self._safe_rpc(self.stub.GetBalance, cryptixwalletd_pb2.GetBalanceRequest(), timeout=self.timeout)

    def new_address(self):
        return self._safe_rpc(self.stub.NewAddress, cryptixwalletd_pb2.NewAddressRequest(), timeout=self.timeout)

    def show_addresses(self):
        return self._safe_rpc(self.stub.ShowAddresses, cryptixwalletd_pb2.ShowAddressesRequest(), timeout=self.timeout)

    def send(self, to_address, amount_sompi, password="", use_existing_change=True, is_send_all=False, fee_policy=None):
        req = cryptixwalletd_pb2.SendRequest(
            toAddress=to_address,
            amount=amount_sompi,
            password=password,
            useExistingChangeAddress=use_existing_change,
            isSendAll=is_send_all
        )
        if fee_policy:
            req.feePolicy.CopyFrom(fee_policy)
        return self._safe_rpc(self.stub.Send, req, timeout=self.timeout)

    def create_unsigned_transactions(self, address, amount_sompi, use_existing_change=True, is_send_all=False, fee_policy=None):
        req = cryptixwalletd_pb2.CreateUnsignedTransactionsRequest(
            address=address,
            amount=amount_sompi,
            useExistingChangeAddress=use_existing_change,
            isSendAll=is_send_all
        )
        if fee_policy:
            req.feePolicy.CopyFrom(fee_policy)
        return self._safe_rpc(self.stub.CreateUnsignedTransactions, req, timeout=self.timeout)

    def broadcast(self, transactions, is_domain=False):
        req = cryptixwalletd_pb2.BroadcastRequest(transactions=transactions, isDomain=is_domain)
        return self._safe_rpc(self.stub.Broadcast, req, timeout=self.timeout)

    def broadcast_replacement(self, transactions, is_domain=False):
        req = cryptixwalletd_pb2.BroadcastRequest(transactions=transactions, isDomain=is_domain)
        return self._safe_rpc(self.stub.BroadcastReplacement, req, timeout=self.timeout)

    def sign(self, unsigned_transactions, password=""):
        req = cryptixwalletd_pb2.SignRequest(unsignedTransactions=unsigned_transactions, password=password)
        return self._safe_rpc(self.stub.Sign, req, timeout=self.timeout)

    def get_external_utxos(self, address):
        req = cryptixwalletd_pb2.GetExternalSpendableUTXOsRequest(address=address)
        return self._safe_rpc(self.stub.GetExternalSpendableUTXOs, req, timeout=self.timeout)

    def get_version(self):
        return self._safe_rpc(self.stub.GetVersion, cryptixwalletd_pb2.GetVersionRequest(), timeout=self.timeout)

    def bump_fee(self, tx_id, password="", use_existing_change=True, fee_policy=None):
        req = cryptixwalletd_pb2.BumpFeeRequest(
            txID=tx_id,
            password=password,
            useExistingChangeAddress=use_existing_change
        )
        if fee_policy:
            req.feePolicy.CopyFrom(fee_policy)
        return self._safe_rpc(self.stub.BumpFee, req, timeout=self.timeout)

    def shutdown(self):
        return self._safe_rpc(self.stub.Shutdown, cryptixwalletd_pb2.ShutdownRequest(), timeout=self.timeout)
    

# -------------------------
# Helpers
# -------------------------
def sompi_to_cpay(amount_sompi):
    return Decimal(amount_sompi) / Decimal(100_000_000)

def cpay_to_sompi(amount_cpay):
    return int(Decimal(amount_cpay) * 100_000_000)

def parse_amount(amount_str):
    amt = amount_str.strip().lower()
    if amt.endswith("s") or amt.endswith("sompi"):
        amt_num = amt.rstrip("s").rstrip("ompi")
        return int(amt_num)
    return cpay_to_sompi(amt)

def format_balance(resp):
    if isinstance(resp, str):
        return resp
    lines = []
    avail = sompi_to_cpay(resp.available)
    pend = sompi_to_cpay(resp.pending)
    lines.append(f"Available: {avail:.8f} CPAY")
    lines.append(f"Pending  : {pend:.8f} CPAY")
    for addr in getattr(resp, 'addressBalances', []):
        addr_avail = sompi_to_cpay(addr.available)
        addr_pend = sompi_to_cpay(addr.pending)
        lines.append(f"{addr.address}: available={addr_avail:.8f}, pending={addr_pend:.8f}")
    return "\n".join(lines)


def parse_and_validate_amount(amount_str):
    try:
        amt = parse_amount(amount_str)
        if amt <= 0:
            raise ValueError("Amount must be positive")
        return amt
    except Exception:
        raise ValueError("Invalid amount format")


# -------------------------
# Command Processor
# -------------------------
unsigned_transactions_list = []
signed_transactions_list = []

command_queue = queue.Queue()
queue_lock = threading.Lock()

import re

ADDRESS_REGEX = re.compile(r"^[A-Za-z0-9\.]{32,64}$")

def parse_and_validate_amount(amount_str):
    try:
        amt = parse_amount(amount_str)
        if amt <= 0:
            raise ValueError("Amount must be positive")
        return amt
    except Exception:
        raise ValueError("Invalid amount format")

def process_command(wallet: CPAYWalletClient, command: str):
    """
    Processes a trigger command and returns the response as JSON.
    The result is also output to the console.
    """
    parts = command.strip().split()
    if not parts:
        result = {"error": "No command received"}
        print(json.dumps(result, indent=2))
        return json.dumps(result)

    cmd = parts[0].lower()
    response = {}

    try:
        if cmd == "balance":
            resp = wallet.get_balance()
            if isinstance(resp, str):
                response = {"error": resp}
            else:
                response = {
                    "available": f"{sompi_to_cpay(resp.available):.8f}",
                    "pending": f"{sompi_to_cpay(resp.pending):.8f}",
                    "addresses": [
                        {
                            "address": addr.address,
                            "available": f"{sompi_to_cpay(addr.available):.8f}",
                            "pending": f"{sompi_to_cpay(addr.pending):.8f}"
                        }
                        for addr in getattr(resp, "addressBalances", [])
                    ]
                }


        elif cmd == "new_address":
            resp = wallet.new_address()
            if isinstance(resp, str):
                response = {"error": resp}
            else:
                response = {"new_address": resp.address}

        elif cmd == "show_addresses":
            resp = wallet.show_addresses()
            if isinstance(resp, str):
                response = {"error": resp}
            else:
                response = {"addresses": list(getattr(resp, "address", []))}

        elif cmd == "send":
            if len(parts) < 3:
                response = {"error": "Usage: send <to_address> <amount> [password]"}
            else:
                to_addr = parts[1]
                if not ADDRESS_REGEX.match(to_addr):
                    response = {"error": "Invalid address format"}
                    print(json.dumps(response, indent=2))
                    return json.dumps(response)

                try:
                    amount = parse_and_validate_amount(parts[2])
                except ValueError as e:
                    response = {"error": str(e)}
                    print(json.dumps(response, indent=2))
                    return json.dumps(response)

                password = parts[3] if len(parts) >= 4 else ""
                
                def send_func():
                    return wallet.send(to_addr, amount, password=password)
                
                resp = process_transaction(send_func)

                if isinstance(resp, str):
                    response = {"error": resp}
                else:
                    response = {"txIDs": list(resp.txIDs)}

        elif cmd == "unsigned":
            if len(parts) < 3:
                response = {"error": "Usage: unsigned <to_address> <amount>"}
            else:
                to_addr = parts[1]
                if not ADDRESS_REGEX.match(to_addr):
                    response = {"error": "Invalid address format"}
                    print(json.dumps(response, indent=2))
                    return json.dumps(response)

                try:
                    amount = parse_and_validate_amount(parts[2])
                except ValueError as e:
                    response = {"error": str(e)}
                    print(json.dumps(response, indent=2))
                    return json.dumps(response)

                resp = wallet.create_unsigned_transactions(to_addr, amount)
                if isinstance(resp, str):
                    response = {"error": resp}
                else:
                    unsigned_transactions_list.extend(resp.unsignedTransactions)
                    response = {"unsigned_transactions_count": len(resp.unsignedTransactions)}

        elif cmd == "sign":
            if not unsigned_transactions_list:
                response = {"error": "No unsigned transactions available"}
            else:
                password = parts[1] if len(parts) >= 2 else ""
                resp = wallet.sign(unsigned_transactions_list, password=password)
                if isinstance(resp, str):
                    response = {"error": resp}
                else:
                    signed_transactions_list.extend(resp.signedTransactions)
                    unsigned_transactions_list.clear()
                    response = {"signed_transactions_count": len(resp.signedTransactions)}

        elif cmd == "broadcast":
            if not signed_transactions_list:
                response = {"error": "No signed transactions available"}
            else:
                resp = wallet.broadcast(signed_transactions_list)
                signed_transactions_list.clear()
                if isinstance(resp, str):
                    response = {"error": resp}
                else:
                    response = {"broadcasted_txIDs": list(resp.txIDs)}

        elif cmd == "broadcast_replace":
            if not signed_transactions_list:
                response = {"error": "No signed transactions available"}
            else:
                resp = wallet.broadcast_replacement(signed_transactions_list)
                signed_transactions_list.clear()
                if isinstance(resp, str):
                    response = {"error": resp}
                else:
                    response = {"broadcast_replacement_txIDs": list(resp.txIDs)}

        elif cmd == "external_utxos":
            if len(parts) < 2:
                response = {"error": "Usage: external_utxos <address>"}
            else:
                addr = parts[1]
                if not ADDRESS_REGEX.match(addr):
                    response = {"error": "Invalid address format"}
                    print(json.dumps(response, indent=2))
                    return json.dumps(response)

                resp = wallet.get_external_utxos(addr)
                if isinstance(resp, str):
                    response = {"error": resp}
                else:
                    response = {
                        "utxos": [
                            {"address": e.address, "amount": f"{sompi_to_cpay(e.utxoEntry.amount):.8f}"}
                            for e in resp.Entries
                        ]
                    }

        elif cmd == "bump_fee":
            if len(parts) < 2:
                response = {"error": "Usage: bump_fee <txid>"}
            else:
                resp = wallet.bump_fee(parts[1])
                if isinstance(resp, str):
                    response = {"error": resp}
                else:
                    response = {"bumped_txIDs": list(resp.txIDs)}

        elif cmd == "version":
            resp = wallet.get_version()
            if isinstance(resp, str):
                response = {"error": resp}
            else:
                response = {"version": resp.version}

        elif cmd == "shutdown":
            wallet.shutdown()
            response = {"message": "Wallet shutdown requested"}

        else:
            response = {"error": f"Unknown command: {cmd}"}

    except Exception as e:
        response = {"error": str(e), "trace": traceback.format_exc()}


    print(json.dumps(response, indent=2))
    return json.dumps(response)


# -------------------------
# Worker thread for sequential processing
# -------------------------
def command_worker(wallet: CPAYWalletClient):
    while True:
        conn, command = command_queue.get()  
        try:
            result = process_command(wallet, command)
            conn.sendall((result + "\n").encode())
        except Exception as e:
            err_msg = f"[ERROR] Worker failed: {e}\n"
            print(err_msg)
            conn.sendall(err_msg.encode())
        finally:
            conn.close()
            command_queue.task_done()


# -------------------------
# TCP Trigger Server
# -------------------------

def tcp_trigger(wallet: CPAYWalletClient, host="127.0.0.1", port=DEFAULT_TRIGGER_PORT):
    print(f"CPAY Wallet Trigger listening on {host}:{port}")

    worker_thread = threading.Thread(target=command_worker, args=(wallet,), daemon=True)
    worker_thread.start()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(5)

    try:
        while True:
            conn, addr = srv.accept()
            try:
                data = b""
                while True:
                    chunk = conn.recv(1024)
                    if not chunk:
                        break
                    data += chunk
                    if b"\n" in data:
                        break

                command = data.decode(errors="ignore").strip()

                if not command:
                    conn.sendall(b"No command received\n")
                    conn.close()
                    continue

                if len(command) > 1024:
                    conn.sendall(b"[ERROR] Command too long\n")
                    conn.close()
                    continue

                if not ALLOWED_CHARS_REGEX.match(command):
                    conn.sendall(b"[ERROR] Invalid characters in command\n")
                    conn.close()
                    continue

                parts = command.split()

                if parts[0] != TRIGGER_PASSWORD:
                    conn.sendall(b"[ERROR] Invalid password\n")
                    conn.close()
                    continue

                command = " ".join(parts[1:])
                print(f"[Trigger] Queued command: {command}")
                command_queue.put((conn, command))

            except Exception as e:
                err_msg = f"[ERROR] Trigger failed: {e}\n"
                print(err_msg)
                conn.sendall(err_msg.encode())
                conn.close()
    finally:
        srv.close()

# -------------------------
# Main
# -------------------------
if __name__ == "__main__":
    wallet = CPAYWalletClient()
    
    test_resp = wallet.get_version()
    if isinstance(test_resp, str) and test_resp.startswith("[ERROR]"):
        print(f"[ERROR] Wallet connection failed: {test_resp}")
        print("Please make sure the wallet daemon is running on localhost:8082.")
        exit(1)
    else:
        print(f"Wallet daemon is reachable, version: {test_resp.version}")

    print("CPAY Full Wallet Client started. Commands via TCP trigger.")
    tcp_trigger(wallet)
