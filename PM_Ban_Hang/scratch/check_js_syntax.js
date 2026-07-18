const fs = require('fs');
const path = require('path');

const filePath = path.join(__dirname, '../templates/payment_gateway.html');
const content = fs.readFileSync(filePath, 'utf8');

// Extract the <script type="module"> block
const scriptRegex = /<script type="module">([\s\S]*?)<\/script>/;
const match = content.match(scriptRegex);

if (match && match[1]) {
    const jsCode = match[1];
    // Remove import statements to check syntax as a classic script (vm.Script doesn't support ESM imports directly in CJS mode)
    const cleanedJsCode = jsCode.replace(/import\s+[\s\S]*?from\s+['"].*?['"];?/g, '/* stripped import */');
    
    // Check syntax by creating a new Function or using vm
    const vm = require('vm');
    try {
        new vm.Script(cleanedJsCode);
        console.log("JAVASCRIPT SYNTAX IS VALID!");
    } catch (err) {
        console.error("JAVASCRIPT SYNTAX ERROR:", err);
        process.exit(1);
    }
} else {
    console.error("Could not find <script type='module'> block");
    process.exit(1);
}
