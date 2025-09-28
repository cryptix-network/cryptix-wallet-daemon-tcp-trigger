# Cryptix Wallet Daemon + Daemon TCP Trigger

Enables automatic generation of wallet addresses, sending coins, broadcasting, and more. Can be used for all automated payment processes, automatic address generation, and monitoring. For example for exchanges.

## Usage

1. Start and sync the Cryptix Node (compatible with Rust and Go Node)
2. Generate a Wallet (cryptixwallet create)
3. Start the Daemon (cryptixwallet start-daemon)
4. Start the TCP Script
5. Send Command via TCP to the Script

### Commands
Check Wallet Version

Query External UTXOs

Broadcast Transaction

Sign Transaction

Create Unsigned Transaction

Send Coins

Show All Addresses

Generate New Address

Check Balance


### Examples

#### Windows:

$tcp = New-Object System.Net.Sockets.TcpClient('127.0.0.1', 9092)
$stream = $tcp.GetStream()
$writer = New-Object System.IO.StreamWriter($stream)
$writer.AutoFlush = $true

$writer.WriteLine("trigger_password_123 balance")
$reader = New-Object System.IO.StreamReader($stream)
$reader.ReadLine()  

$writer.Close()
$reader.Close()
$tcp.Close()


#### Linux:

echo "$PASSWORD balance" | nc $HOST $PORT


#### Returns Json answers

CPAY Wallet Trigger listening on 127.0.0.1:9092


[Trigger] Queued command: balance
{
  "available": 10.0,
  "pending": 0.0,
  "addresses": [
    {
      "address": "cryptix:qp3evkuaxr4nmf99w2894sk86z3zfc5v396fsk8pd6pxw8s2vws5ggvvnwv04",
      "available": 10.0,
      "pending": 0.0
    }
  ]
}


