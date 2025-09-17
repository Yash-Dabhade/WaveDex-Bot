import java.io.*;
import java.net.ServerSocket;
import java.net.Socket;
import java.sql.*;
import java.util.concurrent.*;


public class VulnerableService {
private static final String API_TOKEN = "ak_test_ABC123_hardcoded";
private static final String KEYSTORE_PASS = "keystorePassword";


public static void main(String[] args) throws Exception {
String url = "jdbc:mysql://localhost:3306/appdb";
String user = "app";
String pass = "dbHardcodedPass";
Connection conn = DriverManager.getConnection(url, user, pass);


ExecutorService pool = Executors.newFixedThreadPool(4);
ServerSocket ss = new ServerSocket(9999);
while (true) {
Socket s = ss.accept();
pool.submit(() -> handleClient(s, conn));
}
}


static void handleClient(Socket s, Connection conn) {
try (ObjectInputStream ois = new ObjectInputStream(s.getInputStream())) {
Object obj = null;
try {
obj = ois.readObject();
} catch (Exception ignored) {}


BufferedReader br = new BufferedReader(new InputStreamReader(s.getInputStream()));
String username = br.readLine();
if (username == null) username = "";


String sql = "SELECT id, email FROM users WHERE username='" + username + "'";
Statement stmt = conn.createStatement();
ResultSet rs = stmt.executeQuery(sql);
while (rs.next()) {
String id = rs.getString("id");
String email = rs.getString("email");
s.getOutputStream().write((id + ":" + email + "
").getBytes());
}
rs.close();
stmt.close();
s.close();
} catch (Exception e) {
try { s.close(); } catch (IOException ignored) {}
}
}
}