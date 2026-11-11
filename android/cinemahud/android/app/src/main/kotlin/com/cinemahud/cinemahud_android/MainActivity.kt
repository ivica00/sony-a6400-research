package com.cinemahud.cinemahud_android

import android.app.Activity
import android.app.PendingIntent
import android.provider.OpenableColumns
import android.content.*
import android.hardware.usb.*
import android.os.*
import android.view.WindowManager
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.Executors

class MainActivity : FlutterActivity() {
    private val worker=Executors.newSingleThreadExecutor()
    private val main=Handler(Looper.getMainLooper())
    private val usb by lazy { getSystemService(Context.USB_SERVICE) as UsbManager }
    private val action="com.cinemahud.USB_PERMISSION"
    private var connection:UsbDeviceConnection?=null
    private var iface:UsbInterface?=null
    private var input:UsbEndpoint?=null
    private var output:UsbEndpoint?=null
    private var deviceId:Int?=null
    private var tid=0
    private var carry=ByteArray(0)
    private var pending:MethodChannel.Result?=null
    private var pendingDevice:UsbDevice?=null
    private var lutPicker:MethodChannel.Result?=null
    private var registered=false
    private val receiver=object:BroadcastReceiver(){
        override fun onReceive(context:Context?, intent:Intent?){
            if(intent?.action==action){
                val result=pending ?: return
                val device=pendingDevice
                pending=null;pendingDevice=null
                if(device!=null && usb.hasPermission(device)) open(device,result)
                else result.error("permission","USB camera permission was not granted",null)
            }else if(intent?.action==UsbManager.ACTION_USB_DEVICE_DETACHED){
                @Suppress("DEPRECATION") val device=intent.getParcelableExtra<UsbDevice>(UsbManager.EXTRA_DEVICE)
                if(device?.deviceId==deviceId) worker.execute {close()}
            }
        }
    }
    override fun configureFlutterEngine(engine:FlutterEngine){
        super.configureFlutterEngine(engine)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val filter=IntentFilter(action).apply {addAction(UsbManager.ACTION_USB_DEVICE_DETACHED)}
        if(Build.VERSION.SDK_INT>=33) registerReceiver(receiver,filter,Context.RECEIVER_NOT_EXPORTED)
        else { @Suppress("DEPRECATION") registerReceiver(receiver,filter) }
        registered=true
        MethodChannel(engine.dartExecutor.binaryMessenger,"com.cinemahud/usb").setMethodCallHandler {call,result ->
            when(call.method){
                "pickLut" -> {
                    if(lutPicker!=null) result.error("busy","Document picker already open",null)
                    else {
                        lutPicker=result
                        @Suppress("DEPRECATION")
                        startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {addCategory(Intent.CATEGORY_OPENABLE);type="*/*"},707)
                    }
                }
                "launchOptions" -> result.success(mapOf("bridge" to intent.getStringExtra("bridge"),"effects" to intent.getBooleanExtra("effects",false)))
                "connect" -> {
                    val device=usb.deviceList.values.firstOrNull {d -> d.vendorId==0x054c && (0 until d.interfaceCount).any {d.getInterface(it).interfaceClass==6}}
                    if(pending!=null) result.error("busy","USB permission request already open",null)
                    else if(device==null) result.error("no_camera","No Sony PTP camera. Connect it with OTG and select PC Remote.",null)
                    else if(usb.hasPermission(device)) open(device,result)
                    else {
                        pending=result;pendingDevice=device
                        usb.requestPermission(device,PendingIntent.getBroadcast(this,0,Intent(action).setPackage(packageName),PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT))
                    }
                }
                "disconnect" -> worker.execute {
                    if(connection!=null){try{transact(0x1003,emptyList(),null)}catch(_:Exception){}}
                    close();main.post{result.success(null)}
                }
                "transaction" -> worker.execute {
                    try {
                        val code=call.argument<Number>("code")!!.toInt()
                        val args=call.argument<List<Number>>("args")?.map{it.toLong()} ?: emptyList()
                        val reply=transact(code,args,call.argument<ByteArray>("data"))
                        main.post{result.success(reply)}
                    }catch(e:Exception){close();main.post{result.error("ptp_transport",e.message,null)}}
                }
                else -> result.notImplemented()
            }
        }
    }
    private fun open(device:UsbDevice,result:MethodChannel.Result){worker.execute{
        try{
            close()
            val intf=(0 until device.interfaceCount).map{device.getInterface(it)}.first{it.interfaceClass==6}
            val eps=(0 until intf.endpointCount).map{intf.getEndpoint(it)}.filter{it.type==UsbConstants.USB_ENDPOINT_XFER_BULK}
            val epIn=eps.first{it.direction==UsbConstants.USB_DIR_IN};val epOut=eps.first{it.direction==UsbConstants.USB_DIR_OUT}
            val conn=usb.openDevice(device) ?: error("Cannot open camera")
            if(!conn.claimInterface(intf,true)){conn.close();error("USB interface is busy")}
            connection=conn;iface=intf;input=epIn;output=epOut;deviceId=device.deviceId;tid=0;carry=ByteArray(0)
            main.post{result.success(mapOf("vendorId" to device.vendorId,"productId" to device.productId))}
        }catch(e:Exception){close();main.post{result.error("usb_open",e.message,null)}}
    }}
    private fun close(){
        try{iface?.let{connection?.releaseInterface(it)}}catch(_:Exception){}
        try{connection?.close()}catch(_:Exception){}
        connection=null;iface=null;input=null;output=null;deviceId=null;carry=ByteArray(0)
    }
    private fun container(type:Int,code:Int,id:Int,body:ByteArray)=ByteBuffer.allocate(12+body.size).order(ByteOrder.LITTLE_ENDIAN).putInt(12+body.size).putShort(type.toShort()).putShort(code.toShort()).putInt(id).put(body).array()
    private fun write(bytes:ByteArray){
        val conn=connection ?: error("Camera disconnected");val endpoint=output ?: error("Missing USB output")
        var at=0
        while(at<bytes.size){val n=conn.bulkTransfer(endpoint,bytes,at,minOf(16384,bytes.size-at),2000);if(n<=0)error("USB write failed");at+=n}
    }
    private fun read():ByteArray {
        val conn=connection ?: error("Camera disconnected");val endpoint=input ?: error("Missing USB input")
        val bytes=ByteArrayOutputStream();bytes.write(carry);carry=ByteArray(0)
        var length=-1;val chunk=ByteArray(16384);val deadline=System.nanoTime()+5_000_000_000L
        while(true){
            if(length<0 && bytes.size()>=12){length=ByteBuffer.wrap(bytes.toByteArray(),0,4).order(ByteOrder.LITTLE_ENDIAN).int;if(length<12||length>32*1024*1024)error("Invalid PTP length")}
            if(length>=0 && bytes.size()>=length){val all=bytes.toByteArray();carry=all.copyOfRange(length,all.size);return all.copyOfRange(0,length)}
            if(System.nanoTime()>deadline)error("PTP read deadline")
            val n=conn.bulkTransfer(endpoint,chunk,chunk.size,1000);if(n<0)error("Camera USB read failed or timed out");if(n>0)bytes.write(chunk,0,n)
        }
    }
    private fun transact(code:Int,args:List<Long>,data:ByteArray?):Map<String,Any>{
        check(connection!=null){"Camera disconnected"};require(args.size<=5){"Too many PTP parameters"}
        val id=++tid;val params=ByteBuffer.allocate(args.size*4).order(ByteOrder.LITTLE_ENDIAN);args.forEach{params.putInt(it.toInt())}
        write(container(1,code,id,params.array()));if(data!=null)write(container(2,code,id,data))
        var payload=ByteArray(0)
        repeat(2){
            val packet=read();val h=ByteBuffer.wrap(packet).order(ByteOrder.LITTLE_ENDIAN);h.int
            val type=h.short.toInt() and 0xffff;val response=h.short.toInt() and 0xffff;val responseId=h.int
            check(responseId==id){"PTP transaction mismatch"}
            if(type==3)return mapOf("rc" to response,"data" to payload)
            check(type==2 && response==code && data==null){"Unexpected PTP container"}
            payload=packet.copyOfRange(12,packet.size)
        }
        error("PTP response missing")
    }
    @Deprecated("Activity result compatibility")
    override fun onActivityResult(requestCode:Int,resultCode:Int,data:Intent?){
        super.onActivityResult(requestCode,resultCode,data)
        if(requestCode!=707)return
        val result=lutPicker ?: return
        lutPicker=null
        val uri=data?.data
        if(resultCode!=Activity.RESULT_OK || uri==null){result.success(null);return}
        worker.execute {
            try {
                var name="Imported LUT.cube"
                contentResolver.query(uri,arrayOf(OpenableColumns.DISPLAY_NAME),null,null,null)?.use {cursor -> if(cursor.moveToFirst()) name=cursor.getString(0)}
                val stream=contentResolver.openInputStream(uri) ?: error("Cannot open LUT")
                val buffer=ByteArrayOutputStream()
                stream.use {input -> val chunk=ByteArray(8192);while(true){val count=input.read(chunk);if(count<0)break;buffer.write(chunk,0,count);if(buffer.size()>8*1024*1024)error("LUT exceeds 8 MB")}}
                main.post {result.success(mapOf("name" to name,"bytes" to buffer.toByteArray()))}
            }catch(e:Exception){main.post{result.error("lut_import",e.message,null)}}
        }
    }
    override fun onDestroy(){
        if(registered){try{unregisterReceiver(receiver)}catch(_:Exception){}}
        pending?.error("closed","App closed during USB permission",null);pending=null
        worker.execute{close()};worker.shutdown();super.onDestroy()
    }
}
